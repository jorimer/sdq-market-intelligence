"""Tests de Pensiones (SIPEN) como SectorProduct — productización (F3).

Mono-módulo: implementa el contrato en el propio módulo SIN tocar el framework.
Cubren: conformidad con el contrato, manifiesto de 3 niveles, readiness desde
señales reales (DB vacía → G1/G2 bajan), Pulse NACIONAL anonimizado (las AFP son
firmas → roster con nombres, ninguno se filtra), nivel nombrado por AFP y render.
"""
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    ProductTier,
    SectorProduct,
    assemble_product_report,
    compute_readiness,
    get_product,
    is_implemented,
)
from shared.products.anonymization import enforce_anonymized
from shared.settings.models import AppSetting  # noqa: F401 — registra tabla
from modules.pension_intel.models.models import (
    PensionEntity, PensionRating, PensionSeries, PensionSnapshot,
)
from modules.pension_intel.products import PensionProduct, pension_manifest
from modules.pension_intel.sipen_sync import sipen_pension_sync


# ── Contrato + manifiesto ──

def test_pension_registered_and_contract():
    assert is_implemented("pension")
    assert isinstance(PensionProduct(), SectorProduct)
    assert isinstance(get_product("pension", None), PensionProduct)


def test_pension_manifest_three_tiers():
    m = pension_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"pension_assessment", "recommendation", "limitations"} <= dd


# ── DB en memoria ──

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        PensionEntity.__table__, PensionSeries.__table__,
        PensionRating.__table__, PensionSnapshot.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield s
    finally:
        s.close()


# ── Readiness desde señales reales (no hardcode) ──

def test_pension_readiness_empty_db(db):
    """Sin dato: G1/G2=0 (cobertura/motor reales); G3/G4 (manifiesto) plenos; G5 = doctrina."""
    rep = compute_readiness(PensionProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.5


def test_pension_readiness_no_tables_does_not_crash():
    """Robustez: sin tablas, las lecturas en SAVEPOINT revierten limpio → G1/G2=0."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(PensionProduct(s), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_pension_readiness_with_data(db):
    """Con dato real ingerido: G2=1 (motor) y G1 parcial (<1: solvencia = brecha)."""
    sipen_pension_sync(db)
    rep = compute_readiness(PensionProduct(db), ProductTier.pulse)
    assert rep["g2"] == 1.0
    assert 0.0 < rep["g1"] < 1.0  # cobertura parcial honesta (brecha de solvencia)


# ── Pulse nacional anonimizado (las AFP son firmas) ──

def test_pension_pulse_snapshot_is_anonymous(db):
    sipen_pension_sync(db)
    snap = PensionProduct(db).snapshot(ProductTier.pulse, "")
    assert snap.entity_name is None
    assert len(snap.entity_roster) == 7  # roster = las 7 AFP
    # El payload no lleva ranking ni nombres → el sensor de anonimización pasa.
    enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)


def test_product_pulse_honors_selected_period(db, monkeypatch):
    """Regresión (espejo del PR #552 de seguros): el selector de períodos ofrece la
    historia completa y elegir un período sirve la vista as-of — con la anonimización
    del Pulse intacta (las AFP son firmas)."""
    from modules.pension_intel.tests.test_sipen_sync import _fake_rentabilidad_history

    monkeypatch.setattr("modules.pension_intel.sipen_sync.fetch_sipen_rentabilidad",
                        lambda period=None: _fake_rentabilidad_history())
    sipen_pension_sync(db)

    prod = PensionProduct(db)
    assert len(prod.available_periods()) > 12   # historia, no solo "el último"

    snap = prod.snapshot(ProductTier.pulse, "2023-06")
    assert snap.period == "2023-06"
    assert snap.payload["headline"]["sipen.rentabilidad.cci_nominal_anual"] == 8.5
    # La vista histórica sigue anonimizada: roster con nombres, ninguno en el payload.
    assert snap.entity_name is None
    enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)

    # Sin período → vista más reciente (comportamiento original intacto).
    latest = prod.snapshot(ProductTier.pulse, "")
    assert latest.payload["headline"]["sipen.rentabilidad.cci_nominal_anual"] == 9.4


def test_pension_named_requires_scope(db):
    sipen_pension_sync(db)
    with pytest.raises(ValueError):
        PensionProduct(db).snapshot(ProductTier.insight, "")


def test_pension_named_snapshot_is_afp(db):
    sipen_pension_sync(db)
    snap = PensionProduct(db).snapshot(ProductTier.insight, "", scope="afp_popular")
    assert snap.entity_name == "AFP Popular"
    assert snap.payload["has_data"] is True


def test_pension_scope_options_only_scoreable(db):
    sipen_pension_sync(db)
    opts = PensionProduct(db).scope_options()
    slugs = {o["value"] for o in opts}
    # Solo las 3 AFP calificables se ofrecen como producto nombrado.
    assert slugs == {"afp_popular", "afp_crecer", "afp_siembra"}


# ── Render + ensamblado ──

def test_pension_pulse_assemble_and_render(db, tmp_path):
    sipen_pension_sync(db)
    path = asyncio.run(assemble_product_report(
        PensionProduct(db), ProductTier.pulse, period="", output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_pension_deep_dive_render_synthetic(tmp_path):
    """Render sin DB (vía muestras): narrativas + PDF de Deep Dive con limitations."""
    prod = PensionProduct()
    snap = prod.sample_snapshot(ProductTier.deep_dive)
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "solvencia" in narr["limitations"].lower()
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_pension_templates_are_guarded():
    """Anti-alucinación: cada template del manifiesto es thin y el eje tiene doctrina."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    m = pension_manifest()
    assert "pension_intel" in AXIS_DOCTRINE
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_pension_no_data_narratives_are_honest():
    """Sin dato: no se narra ninguna cifra (G1 baja, no publicable)."""
    from shared.products import ProductSnapshot
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_data": False}, entity_name="AFP X")
    narr = asyncio.run(PensionProduct().narratives(ProductTier.insight, snap))
    assert all(v for v in narr.values())
