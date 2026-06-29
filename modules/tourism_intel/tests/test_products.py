"""Tests del producto Tourism (turismo) como SectorProduct."""
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
from modules.tourism_intel.models.models import TourismScore
from modules.tourism_intel.products import TourismProduct, tourism_manifest
from modules.tourism_intel.service import compute_and_persist


def test_tourism_registered_dedicated_product():
    assert is_implemented("tourism")
    assert isinstance(TourismProduct(), SectorProduct)
    # el slot tourism lo sirve el producto dedicado (ITT), no el corte transversal
    assert isinstance(get_product("tourism", None), TourismProduct)


def test_manifest_three_tiers():
    m = tourism_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


_ARR = {
    2019: {"nonresident": 6000.0, "foreign": 5000.0,
           "regions": {"América del Norte": 3000.0, "Europa": 1200.0, "América del Sur": 800.0}},
    2022: {"nonresident": 6800.0, "foreign": 5500.0,
           "regions": {"América del Norte": 3500.0, "Europa": 1200.0, "América del Sur": 800.0}},
    2025: {"nonresident": 8600.0, "foreign": 7000.0,
           "regions": {"América del Norte": 4400.0, "Europa": 1500.0, "América del Sur": 1100.0}},
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[TourismScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_pulse_snapshot_national_anonymous(db):
    compute_and_persist(db, arrivals_by_year=_ARR)
    p = TourismProduct(db)
    snap = p.snapshot(ProductTier.pulse, period="")
    assert isinstance(snap, ProductSnapshot)
    assert snap.entity_name is None and snap.entity_roster == ()  # nacional, sin firmas
    assert snap.payload["has_score"] and snap.payload["index"]["itt_score"] is not None


def test_sample_and_no_data_narratives():
    p = TourismProduct()
    sample = p.sample_narratives(ProductTier.deep_dive)
    assert "recommendation" in sample and "limitations" in sample
    # sin score → narrativa NO_DATA (no toca el motor IA)
    snap = ProductSnapshot(tier=ProductTier.pulse, period="—",
                           payload={"has_score": False}, entity_name=None, entity_roster=())
    out = asyncio.run(p.narratives(ProductTier.pulse, snap))
    assert "tourism_pulse" in out
