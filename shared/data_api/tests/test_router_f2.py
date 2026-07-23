"""Tests de las rutas F2 — /scores, /signals, /quality — sobre una app mínima.

Lo que se protege: la auto-extensión también aplica a los scores (declarar el score lo
publica, sin tocar la capa API); la narrativa jamás viaja (solo el desglose numérico);
una lista de señales vacía es un resultado, no un hueco; y /quality sirve el MISMO
registro que gobierna el gate de honestidad, con la prosa de procedencia generada.
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
from shared.products.contract import CanonicalScore, ScoreObservation, SignalItem
from shared.products.models import (
    ProductActivation,
    ProductEntitlement,
    ProductReadiness,
    Subscription,
)
from shared.products.registry import CatalogEntry
from shared.registry.signals import REAL, RUBRIC, AxisRegistry, VariableSignal

SECTOR = "macro"


class FakeScoreProduct:
    sector_key = SECTOR

    def __init__(self):
        self.scores = [CanonicalScore(
            code="irmp", label="Índice de Riesgo Macro-Político",
            subject_kind="country", direction="mayor score = menor riesgo",
            subjects=("DOM", "PER"), period_latest="2026-06-30", n_obs=48,
        )]
        self.signals = [SignalItem(
            key="debt_acceleration", label="Aceleración de deuda pública",
            severity="watch", period="2026-05", subject="public_debt_gdp",
            detail="pendiente de 2° orden positiva 3 períodos seguidos",
        )]

    def canonical_scores(self):
        return self.scores

    def score_observations(self, code, *, subject=None, start=None, end=None, limit=None):
        obs = [
            ScoreObservation(subject="DOM", period="2026-06-30", score=61.2,
                             band="moderate",
                             dimensions={"macro": {"score": 70.0, "weight": 0.3,
                                                   "contribution": 21.0}},
                             model_version="1.0"),
            ScoreObservation(subject="PER", period="2026-06-30", score=55.4,
                             band="moderate", dimensions=None, model_version="1.0"),
        ]
        if subject:
            obs = [o for o in obs if o.subject == subject]
        return obs

    def canonical_signals(self, limit=None):
        return self.signals[: limit or None]


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, ApiKey.__table__, ApiUsage.__table__,
        ProductActivation.__table__, ProductReadiness.__table__,
        ProductEntitlement.__table__, Subscription.__table__,
    ])
    db = sessionmaker(bind=engine)()

    user = User(email="pms@sdqconsulting.com.do", password_hash="x",
                full_name="SDQ-PMS", tier=AccessTier.enterprise)
    db.add(user)
    db.add(ProductActivation(sector_key=SECTOR, tier="pulse", is_active=True))
    db.add(ProductReadiness(sector_key=SECTOR, tier="pulse", readiness=0.92))
    db.commit()

    product = FakeScoreProduct()
    entry = CatalogEntry(SECTOR, "Macro de prueba", "macro_monitor", "BCRD")
    monkeypatch.setattr("shared.data_api.manifest.PRODUCT_CATALOG", [entry])
    monkeypatch.setattr("shared.data_api.manifest.is_implemented", lambda k: True)
    monkeypatch.setattr("shared.data_api.manifest.get_product", lambda k, d=None: product)
    monkeypatch.setattr("shared.data_api.router.get_product", lambda k, d=None: product)

    app = FastAPI()
    app.include_router(data_router, prefix="/api/data/v1")
    app.dependency_overrides[get_db] = lambda: db

    created = create_key(db, user_id=user.id, name="SDQ-PMS", client_ref="sdq-pms",
                         usage="internal", rate_limit_per_minute=1000)
    yield {
        "client": TestClient(app), "db": db, "product": product,
        "auth": {"Authorization": f"Bearer {created['token']}"},
    }
    db.close()


# ─── /scores ──────────────────────────────────────────────────────────


def test_declared_score_appears_in_catalog_as_derived(env):
    body = env["client"].get("/api/data/v1/catalog?kind=score", headers=env["auth"]).json()
    assert [a["code"] for a in body["data"]] == ["irmp"]
    a = body["data"][0]
    assert a["derivation"] == "derived" and a["kind"] == "score"
    assert "SDQ" in a["license"]        # licencia propia, no de emisor


def test_scores_serve_the_panel_with_numeric_dimensions(env):
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    assert body["meta"]["score"]["code"] == "irmp"
    dom = next(o for o in body["data"] if o["subject"] == "DOM")
    assert dom["score"] == 61.2 and dom["dimensions"]["macro"]["weight"] == 0.3
    assert any(c["code"] == "derived_asset" for c in body["caveats"])


def test_scores_filter_by_subject(env):
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}?subject=PER",
                             headers=env["auth"]).json()
    assert [o["subject"] for o in body["data"]] == ["PER"]


def test_no_narrative_field_ever_travels(env):
    """La narrativa es el producto de reporte: el payload de scores no tiene campo
    de texto libre más allá de band/reason."""
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    allowed = {"subject", "period", "score", "band", "dimensions", "model_version", "reason"}
    for o in body["data"]:
        assert set(o) <= allowed


def test_unknown_sector_scores_is_404(env):
    r = env["client"].get("/api/data/v1/scores/inexistente", headers=env["auth"])
    assert r.status_code == 404 and r.json()["detail"]["code"] == "score_not_found"


def test_a_second_score_appears_without_touching_the_api(env):
    """Auto-extensión para scores: declarar otro score lo publica solo."""
    env["product"].scores.append(CanonicalScore(
        code="mci", label="Otro índice", subject_kind="country", n_obs=10))
    body = env["client"].get("/api/data/v1/catalog?kind=score", headers=env["auth"]).json()
    assert sorted(a["code"] for a in body["data"]) == ["irmp", "mci"]
    # Con dos scores, el sector exige precisar el código:
    r = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "ambiguous_code"
    r = env["client"].get(f"/api/data/v1/scores/{SECTOR}?code=irmp", headers=env["auth"])
    assert r.status_code == 200


# ─── /signals ─────────────────────────────────────────────────────────


def test_signals_serve_the_deterministic_output(env):
    body = env["client"].get(f"/api/data/v1/signals/{SECTOR}", headers=env["auth"]).json()
    assert body["data"][0]["key"] == "debt_acceleration"
    assert body["data"][0]["severity"] == "watch"


def test_empty_signals_is_a_result_not_a_hole(env):
    env["product"].signals = []
    body = env["client"].get(f"/api/data/v1/signals/{SECTOR}", headers=env["auth"]).json()
    assert body["data"] == []
    assert any(c["code"] == "deterministic_rules" for c in body["caveats"])


# ─── /quality ─────────────────────────────────────────────────────────


def test_quality_serves_the_registry_with_generated_provenance(env, monkeypatch):
    axis = AxisRegistry(
        sector_key=SECTOR, display_name="Macro", source="BCRD", implemented=True,
        period="2026-06",
        signals=(
            VariableSignal(key="gdp", label="crecimiento", state=REAL, weight=0.6),
            VariableSignal(key="ease", label="facilidad", state=RUBRIC, weight=0.4),
        ),
    )

    class FakeRegistry:
        axes = (axis,)

    monkeypatch.setattr("shared.registry.service.build_data_registry",
                        lambda db: FakeRegistry())
    body = env["client"].get(f"/api/data/v1/quality/{SECTOR}", headers=env["auth"]).json()
    d = body["data"]
    assert d["coverage_real"] == 0.6
    assert d["state_counts"] == {"real": 1, "rubric": 1, "gap": 0}
    assert "facilidad" in d["provenance"]           # la prosa GENERADA, no escrita
    assert {v["key"] for v in d["variables"]} == {"gdp", "ease"}


def test_quality_of_unknown_sector_is_404(env, monkeypatch):
    class Empty:
        axes = ()

    monkeypatch.setattr("shared.registry.service.build_data_registry", lambda db: Empty())
    r = env["client"].get("/api/data/v1/quality/desconocido", headers=env["auth"])
    assert r.status_code == 404


# ─── Orden declarado (la trampa que hizo tropezar a PMS) ──────────────


def test_scores_declare_their_order_and_expose_the_current_value(env):
    """PMS leyó data[-1] esperando el vigente y obtuvo el más ANTIGUO: /series va
    ascendente y /scores descendente. El orden ahora viaja declarado, y el vigente se
    sirve directo para que nadie tenga que indexar."""
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}?subject=DOM",
                             headers=env["auth"]).json()
    assert body["meta"]["order"] == "period_desc"
    assert body["meta"]["latest"]["subject"] == "DOM"
    assert body["meta"]["latest"]["period"] == body["data"][0]["period"]


def test_panel_view_has_no_single_latest(env):
    """En el panel cada fila YA es el vigente de su sujeto: un 'latest' único mentiría."""
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    assert body["meta"]["order"] == "period_desc"
    assert body["meta"]["latest"] is None


# ─── Trayectoria discontinua: el hueco se DECLARA ─────────────────────


def test_a_gap_in_the_trajectory_is_declared_not_silent(env):
    """Un consumidor que grafica no puede distinguir 'no hay dato' de 'no se computó'
    si la API no lo dice. El hueco viaja como caveat, con los años faltantes."""
    env["product"].scores[0] = CanonicalScore(
        code="irmp", label="IRMP", subject_kind="country",
        periods=("2019-12-31", "2021-12-31", "2024-12-31"), n_obs=72,
    )
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    gap = next(c for c in body["caveats"] if c["code"] == "sparse_trajectory")
    assert "2020" in gap["message"] and "2022" in gap["message"] and "2023" in gap["message"]
    assert body["meta"]["periods_available"] == ["2019-12-31", "2021-12-31", "2024-12-31"]


def test_a_continuous_trajectory_raises_no_gap_caveat(env):
    env["product"].scores[0] = CanonicalScore(
        code="irmp", label="IRMP", subject_kind="country",
        periods=("2023-12-31", "2024-12-31", "2025-12-31"), n_obs=72,
    )
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    assert "sparse_trajectory" not in [c["code"] for c in body["caveats"]]


def test_mixed_cadences_do_not_invent_an_expectation_of_continuity(env):
    """Con períodos no anuales no se puede afirmar qué 'falta': callar es lo honesto."""
    env["product"].scores[0] = CanonicalScore(
        code="irmp", label="IRMP", subject_kind="country",
        periods=("2025-Q1", "2025-Q3"), n_obs=8,
    )
    body = env["client"].get(f"/api/data/v1/scores/{SECTOR}", headers=env["auth"]).json()
    assert "sparse_trajectory" not in [c["code"] for c in body["caveats"]]
