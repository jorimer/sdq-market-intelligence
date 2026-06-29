"""Tests del producto Free Zones (zonas francas) como SectorProduct."""
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
from modules.free_zones_intel.models.models import FreeZoneScore
from modules.free_zones_intel.products import FreeZoneProduct, free_zones_manifest
from modules.free_zones_intel.service import compute_and_persist


def test_free_zones_registered_dedicated_product():
    assert is_implemented("free_zones")
    assert isinstance(FreeZoneProduct(), SectorProduct)
    # el slot free_zones lo sirve el producto dedicado (IZF), no el corte transversal
    assert isinstance(get_product("free_zones", None), FreeZoneProduct)


def test_manifest_three_tiers():
    m = free_zones_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


_VARS = {
    2021: {"companies": 734, "jobs": 183232, "exports_musd": 7179.6, "investment_musd": 5903.1},
    2024: {"companies": 843, "jobs": 198552, "exports_musd": 8500.3, "investment_musd": 7735.7},
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[FreeZoneScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_pulse_snapshot_national_anonymous(db):
    compute_and_persist(db, vars_by_year=_VARS)
    p = FreeZoneProduct(db)
    snap = p.snapshot(ProductTier.pulse, period="")
    assert isinstance(snap, ProductSnapshot)
    assert snap.entity_name is None and snap.entity_roster == ()  # nacional, sin firmas
    assert snap.payload["has_score"] and snap.payload["index"]["fz_score"] is not None


def test_quarter_period_falls_back_to_latest_annual(db):
    # Producto anual: un período trimestral de la UI cae al último año, no a blanco.
    compute_and_persist(db, vars_by_year=_VARS)
    snap = FreeZoneProduct(db).snapshot(ProductTier.pulse, period="2026-Q1")
    assert snap.payload["has_score"]
    assert snap.payload["index"]["fz_score"] is not None


def test_sample_and_no_data_narratives():
    p = FreeZoneProduct()
    sample = p.sample_narratives(ProductTier.deep_dive)
    assert "recommendation" in sample and "limitations" in sample
    # sin score → narrativa NO_DATA (no toca el motor IA)
    snap = ProductSnapshot(tier=ProductTier.pulse, period="—",
                           payload={"has_score": False}, entity_name=None, entity_roster=())
    out = asyncio.run(p.narratives(ProductTier.pulse, snap))
    assert "free_zones_pulse" in out
