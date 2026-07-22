"""Tests de la Fase 3 — ledger de cambios, webhooks firmados y /forecasts.

Lo que se protege:
- El ledger convierte la auto-extensión en algo consultable: un activo nuevo aparece como
  alta, y uno que desaparece como BAJA (que para un cliente es igual de informativa).
- El aviso de webhook va firmado y NO lleva el dato: verificar la firma es la única
  defensa de una URL que es pública por naturaleza.
- El track record viaja con su tamaño de muestra: 100% de acierto sobre 1 pronóstico no
  puede leerse como 100% de acierto.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import AccessTier, User
from shared.data_api.ledger import changes_since, record_manifest
from shared.data_api.manifest import ExposedAsset
from shared.data_api.models import (
    ApiAssetLedger,
    ApiKey,
    ApiUsage,
    ApiWebhook,
    ApiWebhookDelivery,
)
from shared.data_api.router import router as data_router
from shared.data_api.service import (
    ApiKeyError,
    create_key,
    delete_webhook,
    list_webhooks,
    register_webhook,
    revoke_key,
)
from shared.data_api.webhooks import dispatch, sign_payload, verify_signature
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.contract import CanonicalForecast, ForecastObservation
from shared.products.models import (
    ProductActivation,
    ProductEntitlement,
    ProductReadiness,
    Subscription,
)
from shared.products.registry import CatalogEntry

SECTOR = "macro"
TABLES = [
    User.__table__, ApiKey.__table__, ApiUsage.__table__, ApiAssetLedger.__table__,
    ApiWebhook.__table__, ApiWebhookDelivery.__table__,
    ProductActivation.__table__, ProductReadiness.__table__,
    ProductEntitlement.__table__, Subscription.__table__,
]


def _asset(code, kind="series", exposed=True):
    return ExposedAsset(
        key=f"{SECTOR}:{kind}:{code}", kind=kind, sector_key=SECTOR, code=code,
        label=code.upper(), license="lic", n_obs=40,
        quarantine=() if exposed else ("no_license",),
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.info["factory"] = Session
    try:
        yield s
    finally:
        s.close()


# ─── Ledger de activos ────────────────────────────────────────────────


def test_first_sight_registers_an_addition(db):
    record_manifest(db, [_asset("gdp"), _asset("cpi")])
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    out = changes_since(db, yesterday)
    assert sorted(a["code"] for a in out["added"]) == ["cpi", "gdp"]
    assert out["retired"] == []


def test_a_disappeared_asset_is_retired_not_deleted(db):
    """Para un cliente, la baja es tan informativa como el alta: una serie que dejó de
    publicarse le rompe un modelo en silencio."""
    record_manifest(db, [_asset("gdp"), _asset("cpi")])
    record_manifest(db, [_asset("gdp")])          # cpi desapareció
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    out = changes_since(db, yesterday)
    assert [r["code"] for r in out["retired"]] == ["cpi"]
    assert db.query(ApiAssetLedger).filter_by(code="cpi").one().retired_at is not None


def test_a_returning_asset_is_un_retired_keeping_its_first_seen(db):
    record_manifest(db, [_asset("cpi")])
    first = db.query(ApiAssetLedger).filter_by(code="cpi").one().first_seen_at
    record_manifest(db, [])                        # se va
    record_manifest(db, [_asset("cpi")])           # vuelve
    row = db.query(ApiAssetLedger).filter_by(code="cpi").one()
    assert row.retired_at is None and row.first_seen_at == first


def test_changes_since_the_future_is_empty_not_everything(db):
    record_manifest(db, [_asset("gdp")])
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    out = changes_since(db, tomorrow)
    assert out["added"] == [] and out["retired"] == []


def test_an_unreadable_since_raises_instead_of_lying(db):
    """Devolver 'sin cambios' ante una fecha mal escrita sería la peor respuesta: silencio
    indistinguible de 'no pasó nada'."""
    record_manifest(db, [_asset("gdp")])
    with pytest.raises(ValueError, match="since"):
        changes_since(db, "ayer")


def test_ledger_records_quarantined_assets_too(db):
    record_manifest(db, [_asset("secreta", exposed=False)])
    row = db.query(ApiAssetLedger).filter_by(code="secreta").one()
    assert row.last_exposed is False and row.last_quarantine == "no_license"


def test_visible_keys_scope_the_changes(db):
    """Un activo de un sector que la llave no ve no debe aparecer en sus cambios."""
    record_manifest(db, [_asset("gdp"), _asset("oculta")])
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    out = changes_since(db, yesterday, visible_keys={f"{SECTOR}:series:gdp"})
    assert [a["code"] for a in out["added"]] == ["gdp"]


# ─── Webhooks ─────────────────────────────────────────────────────────


def test_signature_roundtrip():
    body = json.dumps({"event": "macro.updated"}).encode()
    sig = sign_payload("s3cr3t", body)
    assert sig.startswith("sha256=")
    assert verify_signature("s3cr3t", body, sig)
    assert not verify_signature("otro", body, sig)
    assert not verify_signature("s3cr3t", b'{"event":"falso"}', sig)


def test_register_webhook_returns_secret_once_and_hides_it_after(db):
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    hook = register_webhook(db, api_key_id=key["id"], url="https://pms.example/hooks/sdq")
    assert hook["secret"]
    assert "secret" not in list_webhooks(db)[0]


def test_http_and_unknown_events_are_rejected(db):
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    with pytest.raises(ApiKeyError, match="https"):
        register_webhook(db, api_key_id=key["id"], url="http://inseguro.example/h")
    with pytest.raises(ApiKeyError, match="desconocido"):
        register_webhook(db, api_key_id=key["id"], url="https://x.example/h",
                         events="inventado.updated")


def test_dispatch_signs_and_omits_the_data(db, monkeypatch):
    """El aviso dice QUÉ cambió; el dato se pide con la llave. Si el webhook trajera el
    dato sería un segundo canal de acceso con su propia superficie de permisos."""
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    hook = register_webhook(db, api_key_id=key["id"], url="https://pms.example/h",
                            events="macro.updated")

    captured = {}

    class _Resp:
        status_code = 200

    def fake_post(url, content=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = content
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr("shared.data_api.webhooks.httpx.post", fake_post)
    n = dispatch("macro.updated", {"period": "2026-06", "series_count": 315,
                                   "signals": [{"secreto": 1}]},
                 db_factory=lambda: db, background=False)

    assert n == 1
    body = json.loads(captured["body"])
    assert body["event"] == "macro.updated"
    assert body["summary"] == {"period": "2026-06", "series_count": 315}
    assert "signals" not in body["summary"]          # el dato NO viaja
    assert verify_signature(hook["secret"], captured["body"],
                            captured["headers"]["X-SDQ-Signature"])


def test_dispatch_skips_unsubscribed_events(db, monkeypatch):
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    register_webhook(db, api_key_id=key["id"], url="https://pms.example/h",
                     events="esg.updated")
    monkeypatch.setattr("shared.data_api.webhooks.httpx.post",
                        lambda *a, **k: pytest.fail("no debió despachar"))
    assert dispatch("macro.updated", {}, db_factory=lambda: db, background=False) == 0


def test_revoking_the_key_silences_its_webhooks(db, monkeypatch):
    """Revocar la llave corta también los avisos, sin que nadie tenga que acordarse."""
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    register_webhook(db, api_key_id=key["id"], url="https://pms.example/h")
    revoke_key(db, key_id=key["id"], revoked_by=None)
    monkeypatch.setattr("shared.data_api.webhooks.httpx.post",
                        lambda *a, **k: pytest.fail("no debió despachar"))
    assert dispatch("macro.updated", {}, db_factory=lambda: db, background=False) == 0


def test_failed_delivery_is_logged_and_counted(db, monkeypatch):
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    hook = register_webhook(db, api_key_id=key["id"], url="https://caido.example/h")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("shared.data_api.webhooks.httpx.post", boom)
    dispatch("macro.updated", {}, db_factory=lambda: db, background=False)

    row = db.query(ApiWebhook).filter_by(id=hook["id"]).one()
    assert row.consecutive_failures == 1
    delivery = db.query(ApiWebhookDelivery).one()
    assert delivery.error and delivery.status_code is None


def test_webhook_deactivates_itself_after_repeated_failures(db, monkeypatch):
    """Un endpoint muerto no debe costarnos un intento por evento para siempre."""
    from shared.data_api.webhooks import MAX_CONSECUTIVE_FAILURES

    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    hook = register_webhook(db, api_key_id=key["id"], url="https://caido.example/h")
    monkeypatch.setattr("shared.data_api.webhooks.httpx.post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    for _ in range(MAX_CONSECUTIVE_FAILURES):
        dispatch("macro.updated", {}, db_factory=lambda: db, background=False)
    assert db.query(ApiWebhook).filter_by(id=hook["id"]).one().active is False


def test_delete_webhook_removes_its_deliveries(db):
    user = User(email="pms@x.do", password_hash="x", full_name="PMS")
    db.add(user)
    db.commit()
    key = create_key(db, user_id=user.id, name="k")
    hook = register_webhook(db, api_key_id=key["id"], url="https://pms.example/h")
    db.add(ApiWebhookDelivery(webhook_id=hook["id"], event="macro.updated",
                              status_code=200,
                              attempted_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    db.commit()
    delete_webhook(db, webhook_id=hook["id"])
    assert db.query(ApiWebhook).count() == 0 and db.query(ApiWebhookDelivery).count() == 0


# ─── /forecasts y /catalog/changes sobre HTTP ─────────────────────────


class FakeForecastProduct:
    sector_key = SECTOR

    def canonical_forecasts(self):
        return [CanonicalForecast(
            code="tpm", label="Decisión de TPM", target="dirección de la próxima decisión",
            horizon="próxima reunión", classes=("cut", "hold", "hike"),
            n_scored=1, hit_rate=1.0, brier=0.21,
            baseline="clasificador trivial 'siempre mantener': 0.61 de acierto",
        )]

    def forecast_observations(self, code, *, limit=None):
        return [
            ForecastObservation(as_of="2026-06-27", status="pending", predicted="hold",
                                probabilities={"cut": 0.2, "hold": 0.71, "hike": 0.09}),
            ForecastObservation(as_of="2026-05-30", status="scored", predicted="cut",
                                probabilities={"cut": 0.62, "hold": 0.33, "hike": 0.05},
                                realized="cut", correct=True, brier=0.21),
        ]


@pytest.fixture()
def api(db, monkeypatch):
    user = User(email="pms@sdq.do", password_hash="x", full_name="PMS",
                tier=AccessTier.enterprise)
    db.add(user)
    db.add(ProductActivation(sector_key=SECTOR, tier="pulse", is_active=True))
    db.add(ProductReadiness(sector_key=SECTOR, tier="pulse", readiness=0.92))
    db.commit()

    product = FakeForecastProduct()
    entry = CatalogEntry(SECTOR, "Macro", "macro_monitor", "BCRD")
    monkeypatch.setattr("shared.data_api.manifest.PRODUCT_CATALOG", [entry])
    monkeypatch.setattr("shared.data_api.manifest.is_implemented", lambda k: True)
    monkeypatch.setattr("shared.data_api.manifest.get_product", lambda k, d=None: product)
    monkeypatch.setattr("shared.data_api.router.get_product", lambda k, d=None: product)

    app = FastAPI()
    app.include_router(data_router, prefix="/api/data/v1")
    app.dependency_overrides[get_db] = lambda: db
    created = create_key(db, user_id=user.id, name="PMS", usage="internal",
                         rate_limit_per_minute=1000)
    return {"client": TestClient(app), "db": db,
            "auth": {"Authorization": f"Bearer {created['token']}"}}


def test_forecast_carries_its_track_record_and_sample_warning(api):
    body = api["client"].get(f"/api/data/v1/forecasts/{SECTOR}",
                             headers=api["auth"]).json()
    assert body["meta"]["n_scored"] == 1
    assert "small_sample" in [c["code"] for c in body["caveats"]]
    assert "prospective_record" in [c["code"] for c in body["caveats"]]
    pending = next(o for o in body["data"] if o["status"] == "pending")
    assert pending["realized"] is None and pending["predicted"] == "hold"


def test_forecast_descriptor_shows_the_baseline_in_the_catalog(api):
    body = api["client"].get("/api/data/v1/catalog?kind=forecast",
                             headers=api["auth"]).json()
    note = body["data"][0]["note"]
    assert "acierto" in note and "siempre mantener" in note


def test_catalog_populates_the_ledger_and_changes_reports_it(api):
    api["client"].get("/api/data/v1/catalog", headers=api["auth"])
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    body = api["client"].get(f"/api/data/v1/catalog/changes?since={yesterday}",
                             headers=api["auth"]).json()
    assert body["meta"]["added"] >= 1
    assert any(a["code"] == "tpm" for a in body["data"]["added"])


def test_bad_since_is_422_with_a_stable_code(api):
    r = api["client"].get("/api/data/v1/catalog/changes?since=ayer", headers=api["auth"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_since"
