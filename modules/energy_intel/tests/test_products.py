"""Tests del producto Energy (sector #6) como SectorProduct.

Mono-módulo con conector real SIE. Cubren: conformidad, manifiesto, readiness desde
señales reales (DB vacía/sin tablas → G1/G2 bajan; con dato G1 = cobertura del índice
× frescura anual), snapshot nacional anonimizado, render sintético y guard.
"""
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    assemble_product_report,
    compute_readiness,
    get_product,
    is_implemented,
)
from modules.energy_intel.models.models import EnergyScore
from modules.energy_intel.products import EnergyProduct, energy_manifest


def test_energy_registered_and_contract():
    assert is_implemented("energy")
    assert isinstance(EnergyProduct(), SectorProduct)
    assert isinstance(get_product("energy", None), EnergyProduct)


def test_energy_manifest_three_tiers():
    m = energy_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[EnergyScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _dims():
    return {
        "capacity_adequacy": {"score": 100.0, "weight": 0.35, "provenance": "real",
                              "contribution": 35.0},
        "service_quality": {"score": 20.0, "weight": 0.30, "provenance": "real",
                            "contribution": 6.0},
        "energy_transition": {"score": None, "weight": 0.35, "provenance": "brecha",
                              "contribution": None},
    }


def _seed(db):
    db.add(EnergyScore(period="2026", energy_score=63.08, band="Adecuado", coverage=0.65,
                       capacity_mw=7054.05, capacity_score=100.0, service_score=20.0,
                       breakdown={"dimensions": _dims(),
                                  "capacity": {"capacity_mw": 7054.05, "cagr_3y": 7.9, "score": 100.0},
                                  "service": {"backlog_months": 7.8, "score": 20.0}},
                       model_version="1.0"))
    db.commit()


def test_readiness_empty_db(db):
    rep = compute_readiness(EnergyProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.45  # índice preliminar


def test_readiness_no_tables_does_not_crash():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(EnergyProduct(s), ProductTier.pulse)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_readiness_with_data_partial_coverage(db):
    _seed(db)
    rep = compute_readiness(EnergyProduct(db), ProductTier.pulse)
    # G1 = coverage 0.65 × frescura anual plena (2026)
    assert rep["g1"] == pytest.approx(0.65, abs=1e-6)
    assert rep["g2"] == 1.0


def test_pulse_snapshot_is_anonymous(db):
    _seed(db)
    snap = EnergyProduct(db).snapshot(ProductTier.pulse, "2026")
    assert snap.entity_name is None and snap.entity_roster == ()
    assert snap.payload["index"]["energy_score"] == 63.08


def test_named_snapshot_is_sector(db):
    _seed(db)
    snap = EnergyProduct(db).snapshot(ProductTier.deep_dive, "2026")
    assert "Eléctrico" in snap.entity_name


def test_pulse_assemble_and_render(db, tmp_path):
    _seed(db)
    path = asyncio.run(assemble_product_report(
        EnergyProduct(db), ProductTier.pulse, period="2026", output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_deep_dive_render_synthetic(tmp_path):
    index = {"energy_score": 63.08, "band": "Adecuado", "coverage": 0.65,
             "dimensions": _dims(),
             "capacity": {"capacity_mw": 7054.05, "cagr_3y": 7.9, "score": 100.0},
             "service": {"backlog_months": 7.8, "score": 20.0}}
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2026",
                           payload={"has_score": True, "index": index},
                           entity_name="Sector Eléctrico Nacional · RD")
    prod = EnergyProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "IRSE" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_templates_are_guarded():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    assert "energy_intel" in AXIS_DOCTRINE
    m = energy_manifest()
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_no_data_narratives_are_honest():
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_score": False}, entity_name="Sector Eléctrico · RD")
    narr = asyncio.run(EnergyProduct().narratives(ProductTier.insight, snap))
    assert all(v for v in narr.values())
