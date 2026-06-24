"""Tests de los productos sectoriales (sector_intel parametrizado) — #4,#5,#8,#9.

Un mismo SectorIntelProduct sirve a tourism/free_zones/construction/agribusiness.
Cubren: conformidad, manifiesto, readiness desde señales reales (DB vacía/sin tablas
→ G1/G2 bajan; con dato G1 = peso de las 2/5 dims reales, NO hardcode), snapshot
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

PRODUCT_KEYS = ("tourism", "free_zones", "construction", "agribusiness")


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


def _breakdown():
    # sector+macro reales (con score); business/talent/regulation rúbrica (también con
    # score declarado, pero NO cuentan para la cobertura real).
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


def test_readiness_with_data_partial_coverage(db):
    """G1 refleja SOLO el peso de las 2/5 dims reales (sector 0.25 + macro 0.15 = 0.40),
    no hardcode. Cabled-pero-no-publicable: readiness bajo el umbral 0.75."""
    _seed(db, "turismo")
    rep = compute_readiness(SectorIntelProduct(db, "tourism"), ProductTier.pulse)
    assert rep["g1"] == pytest.approx(0.40, abs=1e-6)  # 0.40 real × frescura anual plena
    assert rep["g2"] == 1.0
    assert rep["readiness"] < 0.75  # honesto: no publicable aún


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
    _seed(db, "zonas_francas")
    path = asyncio.run(assemble_product_report(
        SectorIntelProduct(db, "free_zones"), ProductTier.pulse, period="2025",
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
