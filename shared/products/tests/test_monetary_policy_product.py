"""Tests del producto Política Monetaria (sector #, app-level, sin tocar el framework).

Cubre: conformidad + registro, manifiesto de 3 niveles (todos system), snapshot desde
comunicados reales sembrados, narrativa determinista (pulse/forecast) vs IA guardada
(mp_evaluation/recommendation), render PDF+DOCX de la muestra, y anonimización del Pulse.
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
    get_product,
    is_implemented,
)
from modules.macro_monitor.comunicados.models import ComunicadoTPM
from modules.macro_monitor.tpm_modeling.models import TpmForecastLog
from shared.settings.models import AppSetting
from app.products_monetary_policy import MonetaryPolicyProduct


def test_registered_and_contract():
    assert is_implemented("monetary_policy")
    assert isinstance(MonetaryPolicyProduct(), SectorProduct)
    assert isinstance(get_product("monetary_policy", None), MonetaryPolicyProduct)


def test_manifest_three_system_tiers():
    m = MonetaryPolicyProduct().product_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    for t in m.tiers():
        assert m.require_level(t).granularity.value == "system"  # nacional/agregado, sin scope
    deep = m.require_level(ProductTier.deep_dive).sections
    assert "forecast" in deep and "recommendation" in deep and "mp_evaluation" in deep
    assert m.require_level(ProductTier.pulse).sections == ("tpm_snapshot",)


# ── DB con comunicados sembrados ──
@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ComunicadoTPM.__table__, TpmForecastLog.__table__,
                                             AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed(db):
    rows = [(6606, "2026-06-30", "hold", 5.25), (6553, "2025-10-31", "cut", 5.25),
            (6522, "2025-09-30", "cut", 5.50), (6400, "2024-10-31", "cut", 6.00)]
    for aid, d, act, lvl in rows:
        db.add(ComunicadoTPM(article_id=aid, decision_date=d, action=act, tpm_level=lvl,
                             status="ok", title=f"TPM {lvl}", source_url="u"))
    db.commit()


def test_snapshot_pulse_from_real_decisions(db):
    _seed(db)
    snap = MonetaryPolicyProduct(db).snapshot(ProductTier.pulse, "")
    assert snap.entity_name is None
    assert snap.period == "2026-06-30"                       # última decisión
    assert snap.payload["latest"]["tpm"] == 5.25
    assert len(snap.payload["trajectory"]) == 4
    assert "forecast" not in snap.payload                    # pulse no trae pronóstico


def test_snapshot_deep_dive_has_forecast_block(db):
    _seed(db)
    snap = MonetaryPolicyProduct(db).snapshot(ProductTier.deep_dive, "")
    assert "forecast" in snap.payload and "backtest" in snap.payload
    assert snap.payload["forecast"].get("has_model") is False  # sin modelo entrenado → graceful


def test_snapshot_without_decisions_raises(db):
    with pytest.raises(ValueError, match="TPM"):
        MonetaryPolicyProduct(db).snapshot(ProductTier.pulse, "")


def test_data_signals_reflect_real_state(db):
    _seed(db)
    sig = MonetaryPolicyProduct(db).data_signals()
    assert sig.coverage == 1.0 and sig.cadence == "monthly"
    assert "4 decisiones" in sig.detail
    # DB vacía (engine separado) → cobertura 0, honesto.
    e2 = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e2, tables=[ComunicadoTPM.__table__])
    empty = MonetaryPolicyProduct(sessionmaker(bind=e2)()).data_signals()
    assert empty.coverage == 0.0


# ── Narrativa determinista (sin motor) ──
def test_tpm_snapshot_narrative_is_deterministic():
    """El Pulse NO llama al motor IA: narra desde el payload. Corre offline sin monkeypatch."""
    snap = ProductSnapshot(tier=ProductTier.pulse, period="2026-06-30", entity_name=None,
                           payload={"latest": {"fecha": "2026-06-30", "sentido": "hold", "tpm": 5.25},
                                    "cycle": {"ultimos_24m": {"holds": 8, "cortes": 3, "alzas": 0},
                                              "tpm_12_decisiones_atras": 6.75},
                                    "trajectory": [], "eval_context": {}})
    out = asyncio.run(MonetaryPolicyProduct().narratives(ProductTier.pulse, snap))
    assert set(out) == {"tpm_snapshot"}
    assert "5.25%" in out["tpm_snapshot"] and "mantener" in out["tpm_snapshot"].lower()


def test_forecast_section_is_deterministic_with_numbers():
    from app.products_monetary_policy import _forecast_md
    payload = {"forecast": {"has_model": True,
                            "clasificador": {"probabilidades": {"cut": 0.01, "hold": 0.64, "hike": 0.35},
                                             "decision_mas_probable": "hold"},
                            "regla_taylor": {"tasa_implicita": 5.30, "sesgo_pp": 0.05, "sesgo": "neutral"},
                            "caveats": ["No es consejo de inversión."]},
               "backtest": {"classifier": {"macro_f1": 0.56}}, "track_record": {"n_scored": 0}}
    md = _forecast_md(payload)
    assert "64%" in md and "5.30%" in md and "macro-F1 0.56" in md
    assert "acumulación" in md
    # Sin modelo → mensaje honesto, no cifras inventadas.
    assert "no está entrenado" in _forecast_md({"forecast": {"has_model": False}})


# ── Narrativa IA: guardada (template thin + axis en doctrina) ──
def test_ai_sections_are_guarded(monkeypatch):
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
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2026-06-30", entity_name=None,
                           payload={"latest": {"fecha": "2026-06-30", "sentido": "hold", "tpm": 5.25},
                                    "cycle": {}, "trajectory": [], "eval_context": {"has_data": True},
                                    "forecast": {"has_model": True, "clasificador": {},
                                                 "regla_taylor": {}}})
    out = asyncio.run(MonetaryPolicyProduct().narratives(ProductTier.deep_dive, snap))
    # forecast es determinista (no pasa por el motor); mp_evaluation y recommendation sí.
    assert {t for t, _ in calls} == {"mp_evaluation"}
    assert all(t in THIN_TEMPLATES and a in AXIS_DOCTRINE for t, a in calls)
    assert "forecast" in out and "5.30%" not in calls  # forecast no fue al motor


# ── Render PDF + DOCX (muestra curada, sin DB ni motor) ──
def test_render_pulse_sample_pdf(tmp_path):
    prod = MonetaryPolicyProduct()
    snap = prod.sample_snapshot(ProductTier.pulse)
    narr = prod.sample_narratives(ProductTier.pulse)
    path = asyncio.run(prod.render(ProductTier.pulse, snap, narr, sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_render_deep_dive_sample_pdf_and_docx(tmp_path):
    prod = MonetaryPolicyProduct()
    snap = prod.sample_snapshot(ProductTier.deep_dive)
    narr = prod.sample_narratives(ProductTier.deep_dive)
    assert set(narr) == {"mp_evaluation", "forecast", "recommendation"}
    pdf = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr, output_dir=str(tmp_path)))
    docx = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr, output_dir=str(tmp_path), fmt="docx"))
    assert os.path.exists(pdf) and pdf.endswith(".pdf")
    assert os.path.exists(docx) and docx.endswith(".docx")


# ── Anonimización del Pulse ──
def test_pulse_is_anonymous():
    from shared.products.anonymization import enforce_anonymized
    prod = MonetaryPolicyProduct()
    assert prod.product_manifest().require_level(ProductTier.pulse).granularity.value == "system"
    snap = prod.sample_snapshot(ProductTier.pulse)
    assert snap.entity_name is None
    enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)  # no debe levantar


def test_forecast_md_candor_accuracy_vs_baseline():
    """E2E-MM5: la metodología debe exhibir que en accuracy cruda el modelo NO supera
    (iguala) al baseline 'siempre mantener' — no vender el macro-F1 a secas."""
    from app.products_monetary_policy import _forecast_md
    payload = {
        "forecast": {"has_model": True,
                     "clasificador": {"probabilidades": {"cut": 0.01, "hold": 0.64, "hike": 0.35}},
                     "regla_taylor": {}},
        "backtest": {"classifier": {"macro_f1": 0.56, "accuracy": 0.69,
                                    "baseline_always_hold_accuracy": 0.69,
                                    "beats_baseline": False}},
        "track_record": {"has_data": True, "n_scored": 0},
    }
    md = _forecast_md(payload)
    assert "accuracy 0.69 vs 0.69" in md
    assert "iguala" in md
    assert "anticipar los giros" in md
    # MM4: track record vacío presentado como en acumulación, no ambiguo.
    assert "acumulación" in md


# ── Selector de períodos + vista as-of (2026-07-18) ─────────────────────────────
# Regresión: el producto no implementaba available_periods (selector vacío) y el
# snapshot ignoraba el período (servía siempre la última decisión).

def test_available_periods_are_decision_dates(db):
    _seed(db)
    periods = MonetaryPolicyProduct(db).available_periods()
    assert periods == ["2026-06-30", "2025-10-31", "2025-09-30", "2024-10-31"]


def test_snapshot_as_of_historical_period_truncates_trajectory(db):
    _seed(db)
    snap = MonetaryPolicyProduct(db).snapshot(ProductTier.pulse, "2025-09-30")
    assert snap.period == "2025-09-30"                       # la decisión de ese período
    assert snap.payload["latest"]["tpm"] == 5.50
    # As-of: solo las decisiones HASTA esa fecha (2025-09-30 y 2024-10-31).
    fechas = [t["fecha"] for t in snap.payload["trajectory"]]
    assert fechas == ["2025-09-30", "2024-10-31"]
    assert "2026-06-30" not in fechas                        # no filtra el futuro


def test_deep_dive_historical_omits_forecast_with_note(db):
    _seed(db)
    snap = MonetaryPolicyProduct(db).snapshot(ProductTier.deep_dive, "2025-09-30")
    fc = snap.payload["forecast"]
    assert fc.get("has_model") is False
    assert "point-in-time" in fc.get("historical_note", "")   # declara, no fabrica
    assert "backtest" not in snap.payload                     # tampoco backtest retroactivo
    # La narrativa determinista del pronóstico muestra la nota honesta, no el "entrená".
    from app.products_monetary_policy import _forecast_md
    md = _forecast_md(snap.payload)
    assert "point-in-time" in md and "tpm-model-train" not in md


def test_deep_dive_latest_keeps_live_forecast_block(db):
    _seed(db)
    # Período vacío O la última fecha → vista viva con el bloque de modelo.
    for p in ("", "2026-06-30"):
        snap = MonetaryPolicyProduct(db).snapshot(ProductTier.deep_dive, p)
        assert "backtest" in snap.payload and "track_record" in snap.payload
        assert "historical_note" not in snap.payload["forecast"]


def test_mp_evaluation_context_as_of_is_historical(db):
    from modules.macro_monitor.comunicados.service import mp_evaluation_context, trajectory
    _seed(db)
    ctx = mp_evaluation_context(db, as_of="2025-09-30")
    assert ctx["postura_actual"]["fecha"] == "2025-09-30"
    assert ctx["postura_actual"]["tpm"] == 5.50
    assert ctx["ciclo"]["decisiones_en_historico"] == 2       # solo ≤ 2025-09-30
    # trajectory(as_of) coincide.
    assert [t["fecha"] for t in trajectory(db, as_of="2025-09-30")] == \
        ["2025-09-30", "2024-10-31"]
