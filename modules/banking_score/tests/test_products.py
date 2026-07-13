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
from shared.settings.models import AppSetting  # snapshot lee el contrato macro (Entorno Operativo)
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
                        BankingData.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_rating(db, name, score, tier="SDQ-A", period=date(2024, 12, 31), activos=None):
    b = (db.query(Bank).filter(Bank.name == name).one_or_none()
         or Bank(name=name, bank_type=BankType.banca_multiple))
    if b.id is None:
        db.add(b)
        db.flush()
    db.add(RatingResult(bank_id=b.id, period_end=period, overall_score=score,
                        rating_tier=tier, model_type=ModelType.deterministic, model_version="1.0"))
    if activos is not None:
        db.add(BankingData(bank_id=b.id, period_end=period, activos_totales=activos))
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


# ── Pulse ENRIQUECIDO: cifras derivadas de sistema (lección artefacto degradado 2026-06-26) ──

def test_pulse_aggregate_enriched_figures(db):
    """El agregado Pulse sirve cifras derivadas de SISTEMA precalculadas (share por banda,
    núcleo/cola, concentración) + trayectoria vs. período previo — para que la narrativa
    ancle en datos en vez de enumerar lo que le falta."""
    from modules.banking_score.scoring.system_aggregate import system_pulse_aggregate
    # Período previo (promedio más bajo) y actual (más alto) → tendencia ascendente.
    prev = date(2024, 9, 30)
    _seed_rating(db, "Banco Uno SA", 60, period=prev)
    _seed_rating(db, "Banco Dos SA", 64, period=prev)
    _seed_rating(db, "Banco Uno SA", 88, period=date(2024, 12, 31), activos=1000)
    _seed_rating(db, "Banco Dos SA", 70, period=date(2024, 12, 31), activos=400)
    _seed_rating(db, "Banco Tres SA", 40, period=date(2024, 12, 31), activos=100)

    agg = system_pulse_aggregate(db, date(2024, 12, 31))
    cd = agg["cifras_derivadas"]
    assert cd["share_por_banda_pct"] == {"Fuerte": 33.3, "Adecuado": 33.3,
                                         "Vigilancia": 0.0, "Crítico": 33.3}
    assert cd["nucleo_solido_pct"] == 66.7 and cd["cola_de_riesgo_pct"] == 33.3
    # Concentración agregada presente, SIN top10 nominal (anonimización).
    assert cd["concentracion_activos"]["cr5"] is not None
    assert "top10" not in cd["concentracion_activos"]
    # Trayectoria: promedio sube (62 → 66) → dirección 'asciende' y delta precalculado.
    t = agg["tendencia_score"]
    assert t["periodo_previo"] == "2024-09-30" and t["direccion"] == "asciende"
    assert t["delta_pts"] == round(agg["system_avg_score"] - 62.0, 2)
    # Forma canónica que el numeric_guard ya entiende.
    assert cd["variacion_score_actual"]["vs_trimestre_anterior"] == t["delta_pts"]


def test_pulse_aggregate_no_prior_is_honest(db):
    """Un único período → sin trayectoria (None), sin reventar; las cifras de corte siguen."""
    from modules.banking_score.scoring.system_aggregate import system_pulse_aggregate
    _seed_rating(db, "Banco Solo SA", 82, period=date(2024, 12, 31))
    agg = system_pulse_aggregate(db, date(2024, 12, 31))
    assert agg["tendencia_score"] is None
    assert agg["cifras_derivadas"]["nucleo_solido_pct"] == 100.0
    # Sin BankingData sembrada → concentración no disponible, sin reventar (ramas independientes).
    assert "concentracion_activos" not in agg["cifras_derivadas"]


def test_pulse_enriched_payload_stays_anonymized(db):
    """Defensa: las cifras derivadas enriquecidas NO filtran ningún nombre del roster."""
    from shared.products.anonymization import enforce_anonymized
    _seed_rating(db, "Banco Reservas Secreto SA", 88, period=date(2024, 12, 31), activos=900)
    _seed_rating(db, "Banco Popular Secreto SA", 70, period=date(2024, 12, 31), activos=500)
    snap = BankingProduct(db).snapshot(ProductTier.pulse, "2024-12-31")
    assert "cifras_derivadas" in snap.payload
    # No levanta: ningún identificador del roster aparece en el payload narrado.
    enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)


def test_pulse_narrative_passes_enriched_context(db, monkeypatch):
    """La narrativa del Pulse usa el thin 'system_pulse' (no el 'sector_outlook' del IAI) y
    le pasa cifras_derivadas + tendencia_score al motor."""
    from shared.narrative import claude_engine
    captured = {}

    class _Res:
        text = "ok"

    async def _fake_generate(*, context, template, mode, axis, audience):
        captured.update(template=template, axis=axis, ctx=context)
        return _Res()

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    _seed_rating(db, "Banco A SA", 60, period=date(2024, 9, 30))
    _seed_rating(db, "Banco A SA", 88, period=date(2024, 12, 31), activos=700)
    snap = BankingProduct(db).snapshot(ProductTier.pulse, "2024-12-31")
    asyncio.run(BankingProduct(db).narratives(ProductTier.pulse, snap))
    assert captured["template"] == "system_pulse" and captured["axis"] == "banking"
    assert "cifras_derivadas" in captured["ctx"] and "tendencia_score" in captured["ctx"]


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


def test_scope_options_lists_active_entities(db):
    """scope_options alimenta el selector del catálogo: id (value), nombre (label) y tipo
    (group) de las entidades activas CON rating, ordenadas por nombre. value resuelve en
    snapshot(); excluye inactivos y activos sin calificación (que darían 422 al elegirlos)."""
    b1 = _seed_rating(db, "Banco Zeta SA", 80)
    _seed_rating(db, "Banco Alfa SA", 70)
    db.add(Bank(name="Banco Inactivo SA", bank_type=BankType.aap, is_active=False))
    # Activo pero SIN rating → no debe aparecer (snapshot daría 422).
    db.add(Bank(name="Banco Sin Rating SA", bank_type=BankType.banca_multiple, is_active=True))
    db.commit()
    opts = BankingProduct(db).scope_options()
    labels = [o["label"] for o in opts]
    assert labels == ["Banco Alfa SA", "Banco Zeta SA"]   # orden alfabético; sin inactivo ni sin-rating
    assert all(set(o) == {"value", "label", "group"} for o in opts)
    # El value (id) es lo que snapshot(scope=…) resuelve.
    by_value = {o["label"]: o["value"] for o in opts}
    assert by_value["Banco Zeta SA"] == b1.id
    snap = BankingProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope=by_value["Banco Zeta SA"])
    assert snap.entity_name == "Banco Zeta SA"


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


# ── Muestra: exemplar curado tier-1 (no generado al vuelo) ──

def test_sample_narratives_are_curated_and_clean():
    """La muestra usa narrativa CURADA: cubre todas las secciones del nivel, con prosa
    real (no fallback) y sin tokens crudos ni cursivas que el render de Banca no soporta."""
    prod = BankingProduct()
    for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
        sections = banking_manifest().require_level(tier).sections
        narr = prod.sample_narratives(tier)
        assert set(narr) == set(sections), f"{tier.value}: faltan secciones"
        for sec, text in narr.items():
            assert text and "{" not in text, f"{tier.value}/{sec}: placeholder crudo"
            assert "ANTHROPIC_API_KEY" not in text and "automáticamente" not in text
            # El render de Banca solo soporta **negrita**; una cursiva *así* dejaría el
            # asterisco literal en el PDF. El exemplar no debe contener '*' sueltos.
            assert "*" not in text.replace("**", ""), f"{tier.value}/{sec}: cursiva suelta"
    # Coherente con los datos demo (calificación del exemplar).
    assert "SDQ-AA-" in prod.sample_narratives(ProductTier.insight)["executive_summary"]


def test_assemble_sample_uses_curated_narratives(tmp_path):
    """assemble_sample_report toma la narrativa curada (no el motor): el PDF contiene la
    prosa del exemplar, no el texto de fallback."""
    from shared.products.assembler import assemble_sample_report
    path = asyncio.run(assemble_sample_report(BankingProduct(), ProductTier.insight,
                                              output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_limitations_frame_score_as_standalone_not_credit_rating():
    """Fase 3: las Limitaciones encuadran el SDQ como fortaleza financiera standalone,
    no un rating de crédito, sin soporte soberano ni techo país."""
    from modules.banking_score.products import _LIMITATIONS_TEXT
    t = _LIMITATIONS_TEXT.lower()
    assert "standalone" in t
    assert "no es un rating de crédito" in t
    assert "soporte soberano" in t and "techo soberano" in t


# ── Pares NOMBRADOS en el snapshot nombrado (research/tabla comparativa) ──

def _seed_typed(db, name, score, tier, btype, period=date(2024, 12, 31)):
    b = Bank(name=name, bank_type=btype)
    db.add(b)
    db.flush()
    db.add(RatingResult(bank_id=b.id, period_end=period, overall_score=score,
                        rating_tier=tier, model_type=ModelType.deterministic,
                        model_version="1.0"))
    db.commit()
    return b


def test_named_snapshot_includes_named_peers(db):
    """El payload nombrado trae pares NOMBRADOS: posición (sistema y mismo tipo) + líderes
    concretos con score/tier. Complementa el percentil anónimo con la comparación real."""
    _seed_typed(db, "Banco Grande SA", 90, "SDQ-AA", BankType.banca_multiple)
    _seed_typed(db, "Banco Medio SA", 75, "SDQ-A", BankType.banca_multiple)
    subject = _seed_typed(db, "Banco Chico SA", 60, "SDQ-BBB", BankType.banco_ahorro_credito)
    _seed_typed(db, "Financiera Par SA", 55, "SDQ-BBB", BankType.banco_ahorro_credito)

    snap = BankingProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope=subject.id)
    named = (snap.payload.get("peer_block") or {}).get("named_peers")
    assert named, "el payload nombrado debe traer named_peers"
    assert named["n_system"] == 4
    assert named["n_type"] == 2  # los dos banco_ahorro_credito
    rows = named["rows"]
    subj = next(r for r in rows if r["is_subject"])
    assert subj["name"] == "Banco Chico SA"
    assert subj["rank"] == 3 and subj["rank_in_type"] == 1
    # los líderes del sistema aparecen NOMBRADOS con su score/tier real
    by_name = {r["name"]: r for r in rows}
    assert by_name["Banco Grande SA"]["score"] == 90.0
    assert by_name["Banco Grande SA"]["tier"] == "SDQ-AA"
    assert by_name["Banco Grande SA"]["rank"] == 1
    # el id interno NO viaja en el payload (narra nombres, no ids)
    assert all("bank_id" not in r for r in rows)


def test_named_peers_absent_when_single_entity(db):
    """Con una sola entidad calificada no hay pares → no se fabrica tabla."""
    b = _seed_typed(db, "Banco Solo SA", 70, "SDQ-A", BankType.banca_multiple)
    snap = BankingProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope=b.id)
    assert "named_peers" not in (snap.payload.get("peer_block") or {})


def test_pulse_stays_anonymized_with_named_peers_feature(db):
    """Doctrina: el Pulse permanece anonimizado — los pares nombrados son EXCLUSIVOS de
    los niveles nombrados (Insight/Deep Dive)."""
    _seed_typed(db, "Banco Uno SA", 80, "SDQ-A", BankType.banca_multiple)
    _seed_typed(db, "Banco Dos SA", 60, "SDQ-BBB", BankType.banca_multiple)
    snap = BankingProduct(db).snapshot(ProductTier.pulse, "2024-12-31")
    assert "Banco Uno SA" not in str(snap.payload)
