"""Tests del producto Estructura Sectorial (agregado) como SectorProduct."""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    get_product,
    is_implemented,
)
from modules.sector_intel.models.models import SectorVariable
from modules.sector_intel.structure_product import (
    EconomicStructureProduct,
    economic_structure_manifest,
)


def test_registered_dedicated_product():
    assert is_implemented("economic_structure")
    assert isinstance(EconomicStructureProduct(), SectorProduct)
    assert isinstance(get_product("economic_structure", None), EconomicStructureProduct)


def test_in_catalog():
    from shared.products import CATALOG_BY_KEY
    assert "economic_structure" in CATALOG_BY_KEY


def test_manifest_three_tiers():
    m = economic_structure_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SectorVariable.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed(db):
    rows = [
        ("turismo", "sector_size", 8.94), ("turismo", "sector_growth", 3.5),
        ("construccion", "sector_size", 13.45), ("construccion", "sector_growth", -1.8),
        ("financiero", "sector_size", 4.58), ("financiero", "sector_growth", 7.5),
    ]
    for sc, var, val in rows:
        db.add(SectorVariable(sector_code=sc, dimension="sector", variable=var,
                              period="2025", value=val))
    db.commit()


def test_pulse_snapshot_national_anonymous(db):
    _seed(db)
    p = EconomicStructureProduct(db)
    snap = p.snapshot(ProductTier.pulse, period="")
    assert isinstance(snap, ProductSnapshot)
    assert snap.entity_name is None and snap.entity_roster == ()  # nacional, sin firmas
    assert snap.payload["has_data"]
    assert snap.payload["structure"]["top_driver"]["slug"] == "financiero"


def test_data_signals_reports_growth(db):
    _seed(db)
    sig = EconomicStructureProduct(db).data_signals()
    assert sig.coverage and sig.coverage > 0
    assert "VAB" in sig.detail


def test_sample_and_no_data_narratives():
    p = EconomicStructureProduct()
    sample = p.sample_narratives(ProductTier.deep_dive)
    assert "recommendation" in sample and "limitations" in sample
    # sin dato → narrativa NO_DATA (no toca el motor IA)
    snap = ProductSnapshot(tier=ProductTier.pulse, period="—",
                           payload={"has_data": False}, entity_name=None, entity_roster=())
    out = asyncio.run(p.narratives(ProductTier.pulse, snap))
    assert "structure_overview" in out
