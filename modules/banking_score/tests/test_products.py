"""Tests de Banca como SectorProduct (P0.3).

Cubren: conformidad con el contrato, el manifiesto de 3 niveles, el mapeo de bandas
y el agregado de sistema anonimizado (DB en memoria), y el render sintético de los
3 niveles SIN DB (la vía de muestras Banco Demo).
"""
import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra la tabla 'users' (FK de RatingResult)
from shared.database.base import Base
from shared.products import ProductSnapshot, ProductTier, SectorProduct, assemble_product_report
from shared.products.anonymization import AnonymizationError
from modules.banking_score.models.models import (
    Bank, BankingData, BankType, ModelType, RatingResult)
from modules.banking_score.products import BankingProduct, banking_manifest, _parse_period
from modules.banking_score.scoring.system_aggregate import band_for_score


# ── Contrato + manifiesto ──

def test_banking_satisfies_protocol():
    assert isinstance(BankingProduct(), SectorProduct)


def test_manifest_three_tiers_pulse_is_system():
    m = banking_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    assert m.require_level(ProductTier.pulse).watermark == "Vista abierta · SDQMIP"
    # Deep Dive añade riesgo + recomendación + limitaciones sobre Insight.
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    ins = set(m.require_level(ProductTier.insight).sections)
    assert {"risk_assessment", "recommendation", "limitations"} <= dd
    assert ins < dd


# ── Bandas ──

@pytest.mark.parametrize("score,band", [
    (95, "Fuerte"), (80, "Fuerte"), (79.99, "Adecuado"), (65, "Adecuado"),
    (64.99, "Vigilancia"), (45, "Vigilancia"), (44.99, "Crítico"), (0, "Crítico"),
])
def test_band_for_score(score, band):
    assert band_for_score(score) == band


# ── Agregado de sistema (DB en memoria) ──

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, Bank.__table__, RatingResult.__table__,
                        BankingData.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_rating(db, name, score, tier="SDQ-A"):
    b = Bank(name=name, bank_type=BankType.banca_multiple)
    db.add(b)
    db.flush()
    db.add(RatingResult(bank_id=b.id, period_end=date(2024, 12, 31), overall_score=score,
                        rating_tier=tier, model_type=ModelType.deterministic, model_version="1.0"))
    db.commit()
    return b


def test_pulse_snapshot_bands_and_roster(db):
    _seed_rating(db, "Banco Fuerte SA", 88, "SDQ-AA")
    _seed_rating(db, "Banco Adecuado SA", 70, "SDQ-A")
    _seed_rating(db, "Banco Vigilado SA", 50, "SDQ-BBB")
    snap = BankingProduct(db).snapshot(ProductTier.pulse, "2024-12-31")
    assert snap.entity_name is None
    assert snap.payload["band_distribution"] == {"Fuerte": 1, "Adecuado": 1, "Vigilancia": 1, "Crítico": 0}
    assert snap.payload["n_entities"] == 3
    # El roster (nombres) viaja aparte para el sensor, NO en el payload narrado.
    assert "Banco Fuerte SA" in snap.entity_roster
    assert "Banco Fuerte SA" not in str(snap.payload)


def test_pulse_assembler_blocks_leak(db):
    """Si un nombre se cuela en el payload de sistema, el ensamblador lo bloquea."""
    _seed_rating(db, "Banco Test SA", 80, "SDQ-AA-")
    prod = BankingProduct(db)
    orig = prod.snapshot

    def leaky(tier, period, scope=None):
        snap = orig(tier, period, scope)
        snap.payload["nota"] = "Banco Test SA encabeza"  # fuga deliberada
        return snap

    prod.snapshot = leaky
    with pytest.raises(AnonymizationError):
        asyncio.run(assemble_product_report(prod, ProductTier.pulse, period="2024-12-31"))


# ── Señales de readiness que leen DB (G1/G2/G5) ──

def test_parse_period_helper():
    assert _parse_period(None) is None
    assert _parse_period("no-es-fecha") is None         # ValueError → None
    assert _parse_period("2024-12-31") == date(2024, 12, 31)


def test_signals_require_db_raises():
    """Sin sesión de DB, las señales que la necesitan fallan explícitas (no silenciosas)."""
    with pytest.raises(RuntimeError):
        BankingProduct().data_signals()


def test_data_signals_and_engine_with_ratings(db):
    _seed_rating(db, "Banco Uno SA", 80)
    _seed_rating(db, "Banco Dos SA", 65)
    prod = BankingProduct(db)
    health = prod.data_signals()
    assert health.coverage == 1.0
    assert isinstance(health.freshness_days, int) and health.freshness_days > 0
    assert "SIB" in health.sources
    assert "2" in health.detail  # 2 entidades calificadas
    assert prod.has_engine() is True
    val = prod.validation_state()
    assert val.approved is True and val.score == 1.0


def test_data_signals_empty_is_honest(db):
    """DB vacía → cobertura 0, sin frescura, sin motor (no hardcode)."""
    prod = BankingProduct(db)
    health = prod.data_signals()
    assert health.coverage == 0.0 and health.freshness_days is None
    assert prod.has_engine() is False


# ── Snapshot de nivel nombrado (Insight/Deep Dive) ──

def test_named_snapshot_by_name_and_id(db):
    bank = _seed_rating(db, "Banco Nombrado SA", 77, "SDQ-A+")
    prod = BankingProduct(db)
    # Por nombre, período explícito.
    snap = prod.snapshot(ProductTier.insight, "2024-12-31", scope="Banco Nombrado SA")
    assert snap.entity_name == "Banco Nombrado SA"
    assert snap.payload["scoring_result"]["overall_score"] == 77.0
    assert "peer_block" in snap.payload  # None si no hay BankingData (cobertura de la rama)
    # Por id, sin período → cae al último rating.
    snap2 = prod.snapshot(ProductTier.deep_dive, "", scope=bank.id)
    assert snap2.entity_name == "Banco Nombrado SA"


def test_named_snapshot_errors(db):
    prod = BankingProduct(db)
    with pytest.raises(ValueError):                       # falta scope
        prod.snapshot(ProductTier.insight, "2024-12-31")
    with pytest.raises(ValueError):                       # entidad inexistente
        prod.snapshot(ProductTier.insight, "2024-12-31", scope="Fantasma SA")
    # Entidad existe pero sin calificación → error de dominio.
    nb = Bank(name="Banco Sin Rating SA", bank_type=BankType.banca_multiple)
    db.add(nb)
    db.commit()
    with pytest.raises(ValueError):
        prod.snapshot(ProductTier.insight, "2024-12-31", scope="Banco Sin Rating SA")


# ── Sensor guard §5: el Pulse abierto narra cifras CON numeric_guard ──

def test_banking_pulse_narrative_is_guarded(monkeypatch):
    """El Pulse (nivel ABIERTO/público) narra cifras del sistema por un template thin +
    axis en doctrina → numeric_guard (lección 2026-06-23, BLOCKER de P0). Los niveles
    nombrados usan el generador de narrativa establecido de Banca (su propia ruta
    gobernada), no la ruta thin del cerebro."""
    from shared.narrative import claude_engine
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE

    calls = []

    class _Res:
        text = "ok"

    async def _fake_generate(*, context, template, mode, axis, audience):
        calls.append((template, axis))
        return _Res()

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    snap = ProductSnapshot(
        tier=ProductTier.pulse, period="2024-12-31",
        payload={"band_distribution": {"Fuerte": 1, "Adecuado": 0, "Vigilancia": 0, "Crítico": 0},
                 "n_entities": 1, "system_avg_score": 80.0, "period": "2024-12-31"},
        entity_name=None, entity_roster=())
    asyncio.run(BankingProduct().narratives(ProductTier.pulse, snap))
    assert calls, "el Pulse debe narrar al menos una sección con cifras"
    for template, axis in calls:
        assert template in THIN_TEMPLATES, f"{template} no es thin → Pulse narraría sin guard"
        assert axis in AXIS_DOCTRINE, f"{axis} sin doctrina → sin guard"


# ── Render sintético de los 3 niveles (SIN DB — vía muestras) ──

def _demo_scoring():
    return {
        "overall_score": 82.4, "rating_tier": "SDQ-AA-",
        "sub_components": {"solidez": 84, "calidad": 80, "eficiencia": 70,
                           "liquidez": 78, "diversificacion": 62},
        "indicators": {"solvencia": {"raw": 16.8, "score": 90, "available": True},
                       "morosidad": {"raw": 1.9, "score": 85, "available": True}},
    }


def _render_tier(tier, snapshot, tmp_path, sample=True):
    prod = BankingProduct()  # sin DB
    narr = asyncio.run(prod.narratives(tier, snapshot))
    return asyncio.run(prod.render(tier, snapshot, narr, sample=sample, output_dir=str(tmp_path)))


def test_sample_pulse_renders(tmp_path):
    snap = ProductSnapshot(
        tier=ProductTier.pulse, period="2024-12-31",
        payload={"band_distribution": {"Fuerte": 8, "Adecuado": 5, "Vigilancia": 2, "Crítico": 1},
                 "n_entities": 16, "system_avg_score": 72.5, "period": "2024-12-31"},
        entity_name=None, entity_roster=("Banco Demo, S.A.",))
    path = _render_tier(ProductTier.pulse, snap, tmp_path)
    assert os.path.exists(path) and path.endswith(".pdf")


def test_sample_insight_renders(tmp_path):
    snap = ProductSnapshot(
        tier=ProductTier.insight, period="2024-12-31",
        payload={"scoring_result": _demo_scoring(),
                 "peer_block": {"metric_label": "Activos", "cr5": 72.5, "cr10": 88.1, "hhi": 1450}},
        entity_name="Banco Demo, S.A.")
    path = _render_tier(ProductTier.insight, snap, tmp_path)
    assert os.path.exists(path)


def test_pulse_pdf_emits_zero_entity_names(tmp_path):
    """Sensor de anonimización END-TO-END: el PDF Pulse renderizado no contiene ningún
    nombre del roster, y sí las bandas (doctrina: Pulse nunca nombra entidad)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = pytest.importorskip("PyPDF2").PdfReader
    snap = ProductSnapshot(
        tier=ProductTier.pulse, period="2024-12-31",
        payload={"band_distribution": {"Fuerte": 6, "Adecuado": 8, "Vigilancia": 3, "Crítico": 1},
                 "n_entities": 18, "system_avg_score": 71.8, "period": "2024-12-31"},
        entity_name=None, entity_roster=("Banco Demo, S.A.", "Banco Secreto"))
    path = _render_tier(ProductTier.pulse, snap, tmp_path)
    text = "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    assert "Banco Demo" not in text and "Banco Secreto" not in text
    for band in ("Fuerte", "Adecuado", "Vigilancia", "Crítico"):
        assert band in text


def test_sample_deep_dive_has_limitations(tmp_path):
    snap = ProductSnapshot(
        tier=ProductTier.deep_dive, period="2024-12-31",
        payload={"scoring_result": _demo_scoring(), "peer_block": None},
        entity_name="Banco Demo, S.A.")
    prod = BankingProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "SDQ Consulting" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr, sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)
