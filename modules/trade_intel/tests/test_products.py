"""Tests de Comercio (Trade & Logistics) como SectorProduct — sector #3.

Mono-módulo: implementa el contrato en el propio módulo SIN tocar el framework.
Cubren: conformidad con el contrato, manifiesto de 3 niveles, readiness desde
señales reales (DB vacía → G1/G2 bajan = NO hardcode; con dato suben), snapshot
nacional anonimizado (roster vacío, Pulse no nombra firmas) y render sintético.
"""
import asyncio
import os
from datetime import date

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
from shared.settings.models import AppSetting  # noqa: F401 — registra tabla (validation_state)
from modules.trade_intel.models.models import TradeDirection, TradeFlow, TradeScore
from modules.trade_intel.products import TradeProduct, trade_manifest


# ── Contrato + manifiesto ──

def test_trade_registered_and_contract():
    assert is_implemented("trade")
    assert isinstance(TradeProduct(), SectorProduct)
    assert isinstance(get_product("trade", None), TradeProduct)


def test_trade_manifest_three_tiers():
    m = trade_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    assert m.require_level(ProductTier.pulse).watermark == "Vista abierta · SDQMIP"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"geographic_concentration", "recommendation", "limitations"} <= dd


# ── DB en memoria ──

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[TradeFlow.__table__, TradeScore.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_score(db):
    breakdown = {
        "total_exports": 4200.0, "total_imports": 3800.0,
        "n_products_export": 3, "n_products_import": 1,
        "top_export_products": [
            {"product": "instrumentos médicos", "value": 2100.0, "share": 0.5},
            {"product": "ferroníquel", "value": 1200.0, "share": 0.2857},
            {"product": "cigarros", "value": 900.0, "share": 0.2143},
        ],
    }
    db.add(TradeFlow(product="instrumentos médicos", direction=TradeDirection.export,
                     value=2100.0, period="2025", published_at=date.today(), source="DGA"))
    s = TradeScore(period="2025", hhi_exports=0.37, export_diversification=63.0,
                   import_dependency=0.475, resilience_score=60.6, breakdown=breakdown,
                   model_version="1.0")
    db.add(s)
    db.commit()


# ── Readiness desde señales reales (no hardcode) ──

def test_trade_readiness_empty_db(db):
    """Sin score persistido: G1/G2=0 (cobertura/motor reales), G3/G4 (manifiesto) y
    G5 (Gate E firmado, fallback 0.7) reflejan señales reales."""
    rep = compute_readiness(TradeProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.7
    assert abs(rep["readiness"] - (0.15 + 0.15 + 0.15 * 0.7)) < 1e-6


def test_trade_readiness_no_tables_does_not_crash():
    """Robustez (lección Macro): si las tablas del sector no existen, las lecturas en
    SAVEPOINT revierten limpio → G1/G2=0 sin tumbar el recompute compartido."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(TradeProduct(s), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_trade_readiness_with_data(db):
    """Con score fresco: G1 pleno (cobertura 1.0 · frescura ≤120d) y G2=1 (motor)."""
    _seed_score(db)
    rep = compute_readiness(TradeProduct(db), ProductTier.pulse)
    assert rep["g1"] == 1.0 and rep["g2"] == 1.0


# ── Snapshot nacional anonimizado ──

def test_trade_pulse_snapshot_is_anonymous(db):
    _seed_score(db)
    snap = TradeProduct(db).snapshot(ProductTier.pulse, "2025")
    assert snap.entity_name is None and snap.entity_roster == ()
    # capítulos HS presentes (categorías de producto, no firmas — doctrina del dueño)
    assert snap.payload["score"]["top_export_products"]


def test_trade_named_snapshot_is_country(db):
    _seed_score(db)
    snap = TradeProduct(db).snapshot(ProductTier.deep_dive, "2025")
    assert snap.entity_name == "República Dominicana"


# ── Render + ensamblado ──

def test_trade_pulse_assemble_and_render(db, tmp_path):
    _seed_score(db)
    # El ensamblador genérico corre el sensor de anonimización (roster vacío → pasa).
    path = asyncio.run(assemble_product_report(
        TradeProduct(db), ProductTier.pulse, period="2025", output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_trade_deep_dive_render_synthetic(tmp_path):
    """Render sin DB (vía muestras): narrativas + PDF de Deep Dive con limitations."""
    score = {
        "period": "2025", "resilience_score": 60.6, "export_diversification": 63.0,
        "import_dependency": 0.475, "hhi_exports": 0.37,
        "total_exports": 4200.0, "total_imports": 3800.0, "n_products_export": 3,
        "top_export_products": [{"product": "instrumentos médicos", "share": 0.5}],
    }
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                           payload={"has_score": True, "score": score, "partners": None},
                           entity_name="República Dominicana")
    prod = TradeProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "DGA" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_trade_templates_are_guarded():
    """Contrato anti-alucinación (lección 2026-06-23): cada template narrativo del
    manifiesto está en THIN_TEMPLATES y el eje en AXIS_DOCTRINE → numeric_guard. Si
    algún template no fuera thin, narraría cifras por la ruta legacy SIN guard."""
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    m = trade_manifest()
    assert "trade_intel" in AXIS_DOCTRINE
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_trade_no_data_narratives_are_honest():
    """Sin score: no se narra ninguna cifra (G1 baja, no publicable)."""
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_score": False}, entity_name="República Dominicana")
    narr = asyncio.run(TradeProduct().narratives(ProductTier.insight, snap))
    assert all(v for v in narr.values())
