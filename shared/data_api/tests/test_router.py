"""Tests de las rutas ``/api/data/v1`` sobre una app mínima.

Cubre el camino completo del primer cliente: llave → alcance por entitlements → catálogo
→ serie con linaje → cuota agotada. Y las tres cosas que un contrato público no puede
equivocar: no revelar lo que el cliente no puede ver, no imputar faltantes, y no fingir
un corte point-in-time que el linaje no sostiene.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import AccessTier, User
from shared.data_api.models import ApiKey, ApiUsage
from shared.data_api.router import router as data_router
from shared.data_api.service import create_key
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.contract import CanonicalSeries, SeriesObservation
from shared.products.models import (
    ProductActivation,
    ProductEntitlement,
    ProductReadiness,
    Subscription,
)
from shared.products.registry import CatalogEntry

SECTOR = "banking"
LICENSE = "datos oficiales SIB — uso público con cita"


class FakeProduct:
    sector_key = SECTOR

    def __init__(self):
        self.series = [
            CanonicalSeries(
                code="roa", label="Rentabilidad sobre activos", unit="%",
                frequency="quarterly", source="SIB", license=LICENSE,
                period_first="2024-Q1", period_latest="2025-Q1", n_obs=40,
            )
        ]
        self.raise_as_of = False

    def canonical_series(self):
        return self.series

    def series_observations(self, code, *, start=None, end=None, as_of=None, limit=None):
        if as_of and self.raise_as_of:
            raise ValueError(f"La serie '{code}' no tiene fecha de publicación en su linaje.")
        return [
            SeriesObservation(period="2024-Q4", value=1.4, unit="%", source="SIB",
                              published_at="2025-02-01"),
            SeriesObservation(period="2025-Q1", value=None, unit="%", source="SIB",
                              reason="sin dato publicado por la fuente"),
        ]


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, ApiKey.__table__, ApiUsage.__table__,
        ProductActivation.__table__, ProductReadiness.__table__,
        ProductEntitlement.__table__, Subscription.__table__,
    ])
    Session = sessionmaker(bind=engine)
    db = Session()

    user = User(email="pms@sdqconsulting.com.do", password_hash="x",
                full_name="SDQ-PMS", tier=AccessTier.enterprise)
    db.add(user)
    db.add(ProductActivation(sector_key=SECTOR, tier="pulse", is_active=True))
    db.add(ProductReadiness(sector_key=SECTOR, tier="pulse", readiness=0.92))
    db.commit()

    product = FakeProduct()
    entry = CatalogEntry(SECTOR, "Banca de prueba", "banking_score", "SIB")
    monkeypatch.setattr("shared.data_api.manifest.PRODUCT_CATALOG", [entry])
    monkeypatch.setattr("shared.data_api.manifest.is_implemented", lambda k: True)
    monkeypatch.setattr("shared.data_api.manifest.get_product", lambda k, d=None: product)
    monkeypatch.setattr("shared.data_api.router.get_product", lambda k, d=None: product)

    app = FastAPI()
    app.include_router(data_router, prefix="/api/data/v1")
    app.dependency_overrides[get_db] = lambda: db

    created = create_key(db, user_id=user.id, name="SDQ-PMS", client_ref="sdq-pms",
                         rate_limit_per_minute=1000, quota_per_month=1000)
    client = TestClient(app)

    yield {
        "client": client, "db": db, "user": user, "product": product,
        "token": created["token"], "key_id": created["id"],
        "auth": {"Authorization": f"Bearer {created['token']}"},
    }
    db.close()


# ─── Autenticación ────────────────────────────────────────────────────


def test_without_a_key_nothing_is_served(env):
    r = env["client"].get("/api/data/v1/catalog")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "missing_key"


def test_an_invalid_key_is_rejected(env):
    r = env["client"].get("/api/data/v1/catalog",
                          headers={"Authorization": "Bearer sdq_live_aaaaaaaa_" + "b" * 43})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_key"


def test_x_api_key_header_also_works(env):
    r = env["client"].get("/api/data/v1/catalog", headers={"X-API-Key": env["token"]})
    assert r.status_code == 200


def test_a_revoked_key_stops_working(env):
    from shared.data_api.service import revoke_key

    revoke_key(env["db"], key_id=env["key_id"], revoked_by=None)
    r = env["client"].get("/api/data/v1/catalog", headers=env["auth"])
    assert r.status_code == 401 and r.json()["detail"]["code"] == "key_revoked"


def test_errors_are_bilingual_with_a_stable_code(env):
    """Un cliente máquina programa contra el ``code``, no contra el texto."""
    detail = env["client"].get("/api/data/v1/catalog").json()["detail"]
    assert {"code", "message", "message_en"} <= set(detail)


# ─── Catálogo ─────────────────────────────────────────────────────────


def test_catalog_lists_what_this_key_can_read(env):
    body = env["client"].get("/api/data/v1/catalog", headers=env["auth"]).json()
    assert [a["code"] for a in body["data"]] == ["roa"]
    assert body["meta"]["client_ref"] == "sdq-pms"
    assert "license" in body["meta"]


def test_catalog_grows_by_itself_when_the_module_wires_a_series(env):
    """La promesa de auto-extensión, verificada punta a punta sobre HTTP."""
    env["product"].series.append(
        CanonicalSeries(code="nim", label="Margen de intermediación", license=LICENSE,
                        source="SIB", n_obs=30)
    )
    body = env["client"].get("/api/data/v1/catalog", headers=env["auth"]).json()
    assert sorted(a["code"] for a in body["data"]) == ["nim", "roa"]


def test_catalog_hides_quarantined_assets_by_default(env):
    env["product"].series[0] = CanonicalSeries(code="roa", label="ROA", license=None,
                                               source="SIB", n_obs=40)
    body = env["client"].get("/api/data/v1/catalog", headers=env["auth"]).json()
    assert body["data"] == []
    shown = env["client"].get("/api/data/v1/catalog?include_quarantined=true",
                              headers=env["auth"]).json()
    assert shown["data"][0]["quarantine"] == ["no_license"]


def test_a_key_without_access_to_the_sector_sees_nothing(env):
    """No se revela ni la existencia: el sector desaparece, no devuelve 402."""
    env["user"].tier = AccessTier.free
    env["db"].commit()
    env["db"].query(ProductActivation).delete()
    env["db"].commit()
    body = env["client"].get("/api/data/v1/catalog", headers=env["auth"]).json()
    assert body["data"] == []


# ─── Series ───────────────────────────────────────────────────────────


def test_series_returns_observations_with_lineage(env):
    body = env["client"].get("/api/data/v1/series?code=roa", headers=env["auth"]).json()
    assert body["meta"]["series"]["code"] == "roa"
    first = body["data"][0]
    assert first["period"] == "2024-Q4" and first["source"] == "SIB"
    assert first["published_at"] == "2025-02-01"


def test_missing_values_travel_as_null_with_a_reason(env):
    """Nunca se interpola ni se asume cero: un hueco es un hueco declarado."""
    body = env["client"].get("/api/data/v1/series?code=roa", headers=env["auth"]).json()
    gap = body["data"][1]
    assert gap["value"] is None and gap["reason"]
    assert any(c["code"] == "missing_observations" for c in body["caveats"])


def test_unknown_series_is_404(env):
    r = env["client"].get("/api/data/v1/series?code=inexistente", headers=env["auth"])
    assert r.status_code == 404 and r.json()["detail"]["code"] == "series_not_found"


def test_quarantined_series_is_404_not_a_different_error(env):
    """404 uniforme: distinguir 'no existe' de 'está en cuarentena' filtraría el
    catálogo interno."""
    env["product"].series[0] = CanonicalSeries(code="roa", label="ROA", license=None,
                                               source="SIB", n_obs=40)
    r = env["client"].get("/api/data/v1/series?code=roa", headers=env["auth"])
    assert r.status_code == 404


def test_as_of_that_the_lineage_cannot_honor_is_422_not_a_lie(env):
    """Servir el dato de hoy rotulado 'as-of 2024' sería exactamente lo que el corte
    point-in-time existe para evitar."""
    env["product"].raise_as_of = True
    r = env["client"].get("/api/data/v1/series?code=roa&as_of=2024-01-01",
                          headers=env["auth"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "as_of_unsupported"


def test_as_of_adds_an_explicit_caveat(env):
    body = env["client"].get("/api/data/v1/series?code=roa&as_of=2025-06-01",
                             headers=env["auth"]).json()
    assert any(c["code"] == "point_in_time" for c in body["caveats"])


# ─── Cuota ────────────────────────────────────────────────────────────


def test_quota_exhausted_returns_429_with_retry_after(env):
    key = env["db"].query(ApiKey).one()
    key.quota_per_month = 1
    env["db"].commit()
    assert env["client"].get("/api/data/v1/catalog", headers=env["auth"]).status_code == 200
    r = env["client"].get("/api/data/v1/catalog", headers=env["auth"])
    assert r.status_code == 429
    assert r.headers["Retry-After"] and r.json()["detail"]["code"] == "quota_exhausted"


def test_every_call_is_logged_for_audit(env):
    env["client"].get("/api/data/v1/catalog", headers=env["auth"])
    env["client"].get("/api/data/v1/series?code=inexistente", headers=env["auth"])
    rows = env["db"].query(ApiUsage).all()
    assert {r.resource for r in rows} == {"catalog", "series"}
    assert {r.status_code for r in rows} == {200, 404}


# ─── Uso declarado: analizar no es redistribuir ───────────────────────


def test_an_internal_key_receives_non_commercial_sources(env):
    """SDQ-PMS interpreta el mercado con el dato; no lo reexpide. Una fuente
    no-comercial no debe bloquearle el insumo."""
    from shared.data_api.models import ApiKey

    env["product"].series[0] = CanonicalSeries(
        code="mobile_subs", label="Suscripciones móviles", source="ITU",
        license="CC BY-NC-SA 3.0 IGO (ITU)", n_obs=20,
    )
    key = env["db"].query(ApiKey).one()
    key.usage = "internal"
    env["db"].commit()
    body = env["client"].get("/api/data/v1/catalog", headers=env["auth"]).json()
    assert [a["code"] for a in body["data"]] == ["mobile_subs"]
    assert body["meta"]["usage"] == "internal"


def test_an_external_key_does_not_receive_them(env):
    """La misma serie, para un consumidor que podría reexponerla, queda retenida."""
    env["product"].series[0] = CanonicalSeries(
        code="mobile_subs", label="Suscripciones móviles", source="ITU",
        license="CC BY-NC-SA 3.0 IGO (ITU)", n_obs=20,
    )
    body = env["client"].get("/api/data/v1/catalog?include_quarantined=true",
                             headers=env["auth"]).json()
    assert body["data"][0]["quarantine"] == ["license_restricts_redistribution"]


def test_the_default_usage_is_the_conservative_one(env):
    from shared.data_api.models import ApiKey

    assert env["db"].query(ApiKey).one().usage == "external"


def test_an_invalid_usage_is_rejected_at_creation(env):
    from shared.data_api.service import ApiKeyError, create_key

    with pytest.raises(ApiKeyError):
        create_key(env["db"], user_id=env["user"].id, name="mal", usage="lo_que_sea")
