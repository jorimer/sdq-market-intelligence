"""Tests del producto Construction (construcción) como SectorProduct."""
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
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.products import ConstructionProduct, construction_manifest
from modules.construction_intel.service import compute_and_persist


def test_construction_registered_dedicated_product():
    assert is_implemented("construction")
    assert isinstance(ConstructionProduct(), SectorProduct)
    # el slot construction lo sirve el producto dedicado (ICC), no el corte transversal
    assert isinstance(get_product("construction", None), ConstructionProduct)


def test_manifest_three_tiers():
    m = construction_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


def _year(sqm, months=12):
    return {"permits": 100, "sqm": sqm, "investment": sqm * 1000.0, "months": months,
            "by_typology": {"A": 50, "B": 50}, "by_province": {"P": 50, "Q": 50}}


_LIC = {2022: _year(1_000_000), 2025: _year(1_092_727)}
_GROWTH = {2023: 4.0, 2024: 4.0, 2025: 4.0}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ConstructionScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_pulse_snapshot_national_anonymous(db):
    compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    p = ConstructionProduct(db)
    snap = p.snapshot(ProductTier.pulse, period="")
    assert isinstance(snap, ProductSnapshot)
    assert snap.entity_name is None and snap.entity_roster == ()  # nacional, sin firmas
    assert snap.payload["has_score"] and snap.payload["index"]["icc_score"] is not None


def test_quarter_period_falls_back_to_latest_annual(db):
    # Producto anual: un período trimestral de la UI cae al último año, no a blanco.
    compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    snap = ConstructionProduct(db).snapshot(ProductTier.pulse, period="2026-Q1")
    assert snap.payload["has_score"]
    assert snap.payload["index"]["icc_score"] is not None


def test_data_signals_reports_coverage(db):
    compute_and_persist(db, licenses_by_year=_LIC, growth_by_year=_GROWTH)
    h = ConstructionProduct(db).data_signals()
    assert h.coverage == pytest.approx(1.0, abs=1e-6)
    assert h.cadence == "annual"


def test_sample_and_no_data_narratives():
    p = ConstructionProduct()
    sample = p.sample_narratives(ProductTier.deep_dive)
    assert "recommendation" in sample and "limitations" in sample
    # sin score → narrativa NO_DATA (no toca el motor IA)
    snap = ProductSnapshot(tier=ProductTier.pulse, period="—",
                           payload={"has_score": False}, entity_name=None, entity_roster=())
    out = asyncio.run(p.narratives(ProductTier.pulse, snap))
    assert "construction_pulse" in out
