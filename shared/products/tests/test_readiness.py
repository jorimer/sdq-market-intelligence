"""Tests del monitor de readiness (P1): rúbrica G1-G5, gate de activación, servicio.

La rúbrica se prueba con un sector FALSO (señales variables) → demuestra que el
readiness sale de las señales reales del contrato, no de hardcode. El gate y el
servicio se prueban contra DB en memoria. El recálculo integrado usa banking real.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — FK de product_activation
from shared.database.base import Base
from shared.products import (
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    compute_readiness,
    empty_readiness,
)
from shared.products.activation import (
    ACTIVATION_THRESHOLD,
    ActivationError,
    activate,
    can_activate,
    deactivate,
)
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.service import build_matrix, recompute_readiness, sector_detail


# ── Sector falso con señales parametrizables ──

def _manifest():
    full = ("executive_summary",)
    return SectorProductManifest(
        sector_key="banking", display_name="Fake", levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("system_overview",), narrative_templates=("sector_outlook",),
                audience="x", cadence="periodic", base_report_type="sector_outlook"),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=full, narrative_templates=("executive_summary",),
                audience="x", cadence="recurring", base_report_type="full_rating"),
        })


class FakeSector:
    sector_key = "banking"

    def __init__(self, coverage=1.0, freshness=10, engine=True, approved=True, val=1.0):
        self._c, self._f, self._e, self._a, self._v = coverage, freshness, engine, approved, val

    def product_manifest(self):
        return _manifest()

    def data_signals(self):
        return DataHealth(coverage=self._c, freshness_days=self._f, sources=("X",))

    def has_engine(self):
        return self._e

    def validation_state(self):
        return ValidationState(approved=self._a, score=self._v)

    def snapshot(self, tier, period, scope=None):
        return ProductSnapshot(tier=tier, period=period, payload={})

    async def narratives(self, tier, snapshot, lang="es"):
        return {}

    async def render(self, *a, **k):
        return ""


# ── Rúbrica G1-G5 ──

def test_readiness_full_signals_high():
    rep = compute_readiness(FakeSector(), ProductTier.insight)
    assert rep["g1"] == 1.0 and rep["g2"] == 1.0 and rep["g3"] == 1.0
    assert rep["g4"] == 1.0 and rep["g5"] == 1.0
    assert rep["readiness"] == 1.0


def test_readiness_reflects_weak_data_not_hardcode():
    """Bajar cobertura/frescura baja G1 y el readiness — sale de la señal, no de hardcode."""
    weak = compute_readiness(FakeSector(coverage=0.5, freshness=400), ProductTier.insight)
    assert weak["g1"] == 0.0  # cobertura 0.5 × frescura 0 (≥STALE_DAYS)
    # readiness = 1 - peso(G1)*… ; sin G1 → 0.70
    assert weak["readiness"] == pytest.approx(0.70, abs=1e-6)


def test_readiness_no_engine_drops_g2():
    rep = compute_readiness(FakeSector(engine=False), ProductTier.insight)
    assert rep["g2"] == 0.0
    assert rep["readiness"] == pytest.approx(0.75, abs=1e-6)  # 1 - 0.25


def test_readiness_unapproved_validation_zeroes_g5():
    rep = compute_readiness(FakeSector(approved=False, val=0.9), ProductTier.insight)
    assert rep["g5"] == 0.0


def test_empty_readiness_is_zero():
    rep = empty_readiness("energy", ProductTier.pulse, "no cableado")
    assert rep["readiness"] == 0.0 and rep["g1"] == 0.0


# ── Gate de activación ──

def test_thresholds():
    assert ACTIVATION_THRESHOLD[ProductTier.pulse] == 0.75
    assert ACTIVATION_THRESHOLD[ProductTier.insight] == 0.85
    assert ACTIVATION_THRESHOLD[ProductTier.deep_dive] == 0.85


def test_can_activate_gate():
    assert can_activate(0.75, ProductTier.pulse) is True
    assert can_activate(0.84, ProductTier.insight) is False
    assert can_activate(0.85, ProductTier.deep_dive) is True


# ── Servicio + activación contra DB ──

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, ProductReadiness.__table__, ProductActivation.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_readiness(db, sector, tier, value):
    db.add(ProductReadiness(sector_key=sector, tier=tier.value, readiness=value,
                            g1=value, g2=value, g3=value, g4=value, g5=value))
    db.commit()


def test_activate_rejects_below_threshold(db):
    _seed_readiness(db, "banking", ProductTier.insight, 0.80)  # < 0.85
    with pytest.raises(ActivationError, match="no cruza el umbral"):
        activate(db, "banking", ProductTier.insight, user_id=None)


def test_activate_rejects_without_readiness(db):
    with pytest.raises(ActivationError, match="recalcula antes de activar"):
        activate(db, "banking", ProductTier.pulse, user_id=None)


def test_activate_and_deactivate(db):
    _seed_readiness(db, "banking", ProductTier.pulse, 0.80)  # ≥ 0.75
    row = activate(db, "banking", ProductTier.pulse, user_id=None)
    assert row.is_active is True and row.activated_at is not None
    row = deactivate(db, "banking", ProductTier.pulse)
    assert row.is_active is False


# ── Recálculo integrado (banking real) ──

def test_recompute_and_matrix_with_banking(db):
    import modules.banking_score.products  # noqa: F401 — registra banking
    from modules.banking_score.models.models import Bank, RatingResult
    # banking lee sus tablas (data_signals/has_engine) → crearlas en la misma DB.
    Base.metadata.create_all(db.get_bind(), tables=[Bank.__table__, RatingResult.__table__])
    res = recompute_readiness(db)
    assert res["recomputed"] == 30  # 10 sectores × 3 niveles
    matrix = build_matrix(db)
    assert len(matrix["sectors"]) == 10
    banking = next(s for s in matrix["sectors"] if s["sector_key"] == "banking")
    energy = next(s for s in matrix["sectors"] if s["sector_key"] == "energy")
    assert banking["implemented"] is True
    assert energy["implemented"] is False
    # Energy (no cableado) → readiness 0 en los 3 niveles, no activable.
    assert all(lv["readiness"] == 0.0 and lv["can_activate"] is False for lv in energy["levels"])
    # Banking calcula gates reales (G3/G4 del manifiesto = 1.0).
    bp = next(lv for lv in banking["levels"] if lv["tier"] == "pulse")
    assert bp["gates"]["g3"] == 1.0 and bp["gates"]["g4"] == 1.0
    assert sector_detail(db, "banking")["sector_key"] == "banking"
