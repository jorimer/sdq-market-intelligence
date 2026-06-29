"""Tests de los productos sectoriales (sector_intel parametrizado) — #4,#5,#8,#9.

Un mismo SectorIntelProduct sirve a tourism/free_zones/construction/agribusiness.
Cubren: conformidad, manifiesto, readiness desde señales reales (DB vacía/sin tablas
→ G1/G2 bajan; con dato G1 = peso del IAI con procedencia real por-variable, ~0.70 con
6/9 live, NO hardcode; legacy sin procedencia cae al fallback 0.40), snapshot
nacional anonimizado, render sintético y contrato del guard.
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
from modules.sector_intel.models.models import SectorScore
from modules.sector_intel.products import (
    SECTOR_PRODUCTS,
    SectorIntelProduct,
    sector_manifest,
)

PRODUCT_KEYS = ("tourism", "construction", "agribusiness")


def test_all_four_registered_and_contract():
    for pk in PRODUCT_KEYS:
        assert is_implemented(pk)
        prod = get_product(pk, None)
        assert isinstance(prod, SectorProduct)
        assert isinstance(prod, SectorIntelProduct)
        assert prod.sector_key == pk


def test_unknown_product_key_rejected():
    with pytest.raises(ValueError):
        SectorIntelProduct(None, "not_a_sector")


def test_manifest_three_tiers():
    m = sector_manifest("tourism", "Turismo · RD")
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"momentum", "recommendation", "limitations"} <= dd


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SectorScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _var(raw, source):
    return {"raw": raw, "normalized": 50.0, "inverted": False, "source": source}


def _breakdown():
    # Breakdown MODERNO con procedencia por variable (lo que estampa compute_and_persist).
    # 6/9 variables live → cobertura honesta ≈ 0.70 (cada dim a medias = medio peso):
    #   sector(0.15)·2/2 + macro(0.25)·1/1 + business(0.25)·1/2 + talent(0.20)·1/2
    #   + regulation(0.15)·1/2 = 0.70
    return {
        "macro": {"score": 66.7, "weight": 0.25, "contribution": 16.7,
                  "variables": {"macro_exposure": _var(59.0, "live")}},
        "business": {"score": 75.0, "weight": 0.25, "contribution": 18.75,
                     "variables": {"ease_of_business": _var(50.0, "rubric"),
                                   "operating_cost": _var(26113.0, "live")}},
        "talent": {"score": 37.9, "weight": 0.20, "contribution": 7.57,
                   "variables": {"labor_availability": _var(406844.0, "live"),
                                 "skills_index": _var(50.0, "rubric")}},
        "regulation": {"score": 50.0, "weight": 0.15, "contribution": 7.5,
                       "variables": {"regulatory_quality": _var(58.1, "live"),
                                     "regulatory_volatility": _var(50.0, "rubric")}},
        "sector": {"score": 60.7, "weight": 0.15, "contribution": 9.1,
                   "variables": {"sector_growth": _var(3.5, "live"),
                                 "sector_size": _var(8.9, "live")}},
    }


def _legacy_breakdown():
    # Breakdown LEGACY (pre-procedencia): dims con score/weight pero SIN variables.
    # Fallback conservador → solo sector+macro acreditan (0.25+0.15 = 0.40).
    return {
        "sector": {"score": 70.0, "weight": 0.25, "contribution": 17.5},
        "macro": {"score": 55.0, "weight": 0.15, "contribution": 8.25},
        "business": {"score": 50.0, "weight": 0.20, "contribution": 10.0},
        "talent": {"score": 50.0, "weight": 0.20, "contribution": 10.0},
        "regulation": {"score": 50.0, "weight": 0.20, "contribution": 10.0},
    }


def _seed(db, sector_code="turismo"):
    db.add(SectorScore(sector_code=sector_code, period="2025", iai_score=55.75,
                       iai_band="Media", sgps_score=62.0, iai_breakdown=_breakdown(),
                       sgps_breakdown={"historical": 60.0, "structural": 64.0},
                       model_version="1.0"))
    db.commit()


def test_readiness_empty_db(db):
    rep = compute_readiness(SectorIntelProduct(db, "tourism"), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.5  # Gate E sectorial diferido


def test_readiness_no_tables_does_not_crash():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(SectorIntelProduct(s, "construction"), ProductTier.pulse)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_readiness_honest_coverage_by_provenance(db):
    """G1 acredita el peso del IAI con dato real por PROCEDENCIA por-variable (6/9 live
    → ~0.70), no un conjunto fijo de dims. Con esa cobertura el Pulse cruza 0.75."""
    _seed(db, "turismo")
    rep = compute_readiness(SectorIntelProduct(db, "tourism"), ProductTier.pulse)
    assert rep["g1"] == pytest.approx(0.70, abs=1e-6)  # 0.70 real × frescura anual plena
    assert rep["g2"] == 1.0
    # 0.30·0.70 + 0.25 + 0.15 + 0.15 + 0.15·0.50 = 0.835 → cruza el umbral Pulse (0.75).
    assert rep["readiness"] == pytest.approx(0.835, abs=1e-6)
    assert rep["readiness"] >= 0.75


def test_live_vars_counts_national_signal():
    """_live_vars separa las live nacionales (regulatory_*) de las per-sector, para que
    el linaje no sobre-venda el cruce de umbral como profundidad real."""
    from modules.sector_intel.products import _live_vars
    bd = {
        "sector": {"variables": {"sector_growth": {"source": "live"},
                                 "sector_size": {"source": "live"}}},
        "regulation": {"variables": {"regulatory_quality": {"source": "live"},
                                     "regulatory_volatility": {"source": "live"}}},
        "talent": {"variables": {"labor_availability": {"source": "live"},
                                 "skills_index": {"source": "rubric"}}},
    }
    live, total, national = _live_vars(bd)
    assert (live, total, national) == (5, 6, 2)  # 2 nacionales: regulatory_quality/volatility


def test_readiness_legacy_breakdown_fallback(db):
    """Breakdown legacy (sin procedencia) → fallback conservador sector+macro = 0.40,
    para no inflar la cobertura antes del re-backfill que estampa la procedencia."""
    db.add(SectorScore(sector_code="construccion", period="2025", iai_score=55.0,
                       iai_band="Media", sgps_score=60.0, iai_breakdown=_legacy_breakdown(),
                       sgps_breakdown={}, model_version="1.0"))
    db.commit()
    rep = compute_readiness(SectorIntelProduct(db, "construction"), ProductTier.pulse)
    assert rep["g1"] == pytest.approx(0.40, abs=1e-6)
    assert rep["readiness"] < 0.75  # sin procedencia: no publicable aún


def test_pulse_snapshot_is_anonymous(db):
    _seed(db, "turismo")
    snap = SectorIntelProduct(db, "tourism").snapshot(ProductTier.pulse, "2025")
    assert snap.entity_name is None and snap.entity_roster == ()
    assert snap.payload["latest"]["iai_score"] == 55.75


def test_named_snapshot_is_sector(db):
    _seed(db, "agropecuario")
    snap = SectorIntelProduct(db, "agribusiness").snapshot(ProductTier.deep_dive, "2025")
    assert "Agropecuario" in snap.entity_name
    assert "sgps_detail" in snap.payload


def test_pulse_assemble_and_render(db, tmp_path):
    _seed(db, "construccion")
    path = asyncio.run(assemble_product_report(
        SectorIntelProduct(db, "construction"), ProductTier.pulse, period="2025",
        output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_deep_dive_render_synthetic(tmp_path):
    latest = {"sector_code": "turismo", "period": "2025", "iai_score": 55.75,
              "iai_band": "Media", "sgps_score": 62.0, "iai_breakdown": _breakdown()}
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                           payload={"has_score": True, "latest": latest,
                                    "sgps_detail": {"historical": 60.0, "structural": 64.0}},
                           entity_name="Turismo (Hoteles/Bares/Rest.) · RD")
    prod = SectorIntelProduct(None, "tourism")
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "IAI" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_templates_are_guarded():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    assert "sector_intel" in AXIS_DOCTRINE
    m = sector_manifest("tourism", "Turismo · RD")
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_no_data_narratives_are_honest():
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_score": False}, entity_name="Construcción · RD")
    narr = asyncio.run(SectorIntelProduct(None, "construction").narratives(
        ProductTier.insight, snap))
    assert all(v for v in narr.values())


def test_catalog_keys_match_registry():
    """Las 4 product_keys del mapa están en el catálogo del framework."""
    from shared.products import CATALOG_BY_KEY
    for pk in SECTOR_PRODUCTS:
        assert pk in CATALOG_BY_KEY
