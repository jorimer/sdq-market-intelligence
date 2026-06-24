"""Tests del producto Telecom (sector #7) como SectorProduct.

Mono-módulo con conector real INDOTEL. Cubren: conformidad, manifiesto, readiness
(DB vacía/sin tablas → G1/G2 bajan; con dato cobertura plena pero frescura baja por
antigüedad del boletín), snapshot nacional anonimizado, render y guard.
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
from modules.telecom_intel.models.models import TelecomScore
from modules.telecom_intel.products import TelecomProduct, telecom_manifest


def test_telecom_registered_and_contract():
    assert is_implemented("telecom")
    assert isinstance(TelecomProduct(), SectorProduct)
    assert isinstance(get_product("telecom", None), TelecomProduct)


def test_telecom_manifest_three_tiers():
    m = telecom_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"recommendation", "limitations"} <= dd


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[TelecomScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _dims():
    return {
        "mobile_penetration": {"score": 100.0, "weight": 0.30, "provenance": "real", "contribution": 30.0},
        "internet_penetration": {"score": 89.1, "weight": 0.40, "provenance": "real", "contribution": 35.6},
        "broadband_quality": {"score": 86.9, "weight": 0.30, "provenance": "real", "contribution": 26.1},
    }


def _metrics():
    return {"mobile_penetration": 104.7, "internet_penetration": 89.1, "broadband_share": 86.9,
            "revenue_growth": 6.95, "lines_total": 11265937, "internet_total": 9584953}


def _seed(db):
    db.add(TelecomScore(period="2022-Q1", telecom_score=91.7, band="Fuerte", coverage=1.0,
                        mobile_penetration=104.7, internet_penetration=89.1, broadband_share=86.9,
                        breakdown={"dimensions": _dims(), "metrics": _metrics()},
                        model_version="1.0"))
    db.commit()


def test_readiness_empty_db(db):
    rep = compute_readiness(TelecomProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.55


def test_readiness_no_tables_does_not_crash():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(TelecomProduct(s), ProductTier.pulse)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_readiness_with_stale_data_low_freshness(db):
    """Cobertura plena (3/3) pero el boletín 2022-Q1 está rezagado → G1 cae por frescura
    (cadencia trimestral): honesto, cableado-pero-no-publicable."""
    _seed(db)
    rep = compute_readiness(TelecomProduct(db), ProductTier.pulse)
    assert rep["g2"] == 1.0
    assert rep["g1"] == 0.0  # 2022-Q1 en 2026 → >> STALE_DAYS trimestral → frescura 0


def test_pulse_snapshot_is_anonymous(db):
    _seed(db)
    snap = TelecomProduct(db).snapshot(ProductTier.pulse, "2022-Q1")
    assert snap.entity_name is None and snap.entity_roster == ()
    assert snap.payload["index"]["telecom_score"] == 91.7


def test_named_snapshot_is_sector(db):
    _seed(db)
    snap = TelecomProduct(db).snapshot(ProductTier.deep_dive, "2022-Q1")
    assert "Telecomunicaciones" in snap.entity_name


def test_pulse_assemble_and_render(db, tmp_path):
    _seed(db)
    path = asyncio.run(assemble_product_report(
        TelecomProduct(db), ProductTier.pulse, period="2022-Q1", output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_deep_dive_render_synthetic(tmp_path):
    index = {"telecom_score": 91.7, "band": "Fuerte", "coverage": 1.0,
             "dimensions": _dims(), "metrics": _metrics()}
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2022-Q1",
                           payload={"has_score": True, "index": index},
                           entity_name="Sector Telecomunicaciones · RD")
    prod = TelecomProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "INDOTEL" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_templates_are_guarded():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    assert "telecom_intel" in AXIS_DOCTRINE
    m = telecom_manifest()
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_no_data_narratives_are_honest():
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_score": False}, entity_name="Sector Telecom · RD")
    narr = asyncio.run(TelecomProduct().narratives(ProductTier.insight, snap))
    assert all(v for v in narr.values())
