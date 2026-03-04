"""SDQ Banking Scoring Engine — 19 financial indicators across 5 sub-components.

Extracted and refactored from financial-analysis-agent/banking_scoring_service.py.
This module is DB-agnostic: it operates on plain data objects and returns dicts.
Persistence and event publishing happen in the API layer or a service wrapper.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.banking_score.scoring.rating_scale import (
    map_rating_tier,
    get_tier_color,
)
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS,
    DIVERSIFICACION_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    SOLIDEZ_INDICATORS,
    SUB_COMPONENT_WEIGHTS,
)

logger = logging.getLogger("sdq.scoring.engine")


# ─── Helpers ────────────────────────────────────────────────────


def _safe_div(numerator, denominator, default: float = 0.0) -> float:
    """Safe division returning *default* when denominator is zero or None."""
    if denominator is None or denominator == 0:
        return default
    if numerator is None:
        return default
    return float(numerator) / float(denominator)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* between *lo* and *hi*."""
    return max(lo, min(hi, value))


# ─── Data protocol ──────────────────────────────────────────────
# The engine expects any object whose attributes match the field names
# listed below.  This can be a SQLAlchemy model, a dataclass, a
# SimpleNamespace, or a Pydantic model.


@dataclass
class BankingDataInput:
    """Minimal data contract for the scoring engine.

    All monetary values are in the bank's reporting currency (DOP).
    Ratios like ``hhi_sectorial_raw`` and ``hhi_ingresos_raw`` are raw HHI values.
    """
    patrimonio_tecnico: float = 0.0
    apr: float = 0.0
    capital_primario: float = 0.0
    exposicion_total: float = 0.0
    capital_tier1: float = 0.0
    contingentes: float = 0.0
    riesgo_mercado: float = 0.0
    provisiones: float = 0.0
    cartera_vencida_90d: float = 0.0
    activos_totales: float = 0.0
    cartera_bruta: float = 0.0
    cartera_categoria_a: float = 0.0
    cartera_total: float = 0.0
    suma_top10: float = 0.0
    hhi_sectorial_raw: float = 0.0
    castigos: float = 0.0
    exposicion_re: float = 0.0
    cartera_a_prev: float = 0.0
    utilidad_neta: float = 0.0
    activos_promedio: float = 0.0
    patrimonio_promedio: float = 0.0
    ingresos_financieros: float = 0.0
    gastos_financieros: float = 0.0
    activos_productivos_avg: float = 0.0
    gastos_operacionales: float = 0.0
    ingresos_operacionales: float = 0.0
    caja_valores: float = 0.0
    pasivos_cp: float = 0.0
    cartera_neta: float = 0.0
    depositos_totales: float = 0.0
    activos_liquidos: float = 0.0
    pasivos_exigibles: float = 0.0
    hhi_ingresos_raw: float = 0.0


# ─── Indicator result type ──────────────────────────────────────

IndicatorResult = Dict[str, float]  # {"raw": float, "score": float}


# ─── Individual indicator calculations ──────────────────────────
# Each function receives a data object and returns {"raw", "score"}.
# The score is always in [0, 100].
# Formulas extracted EXACTLY from monolith banking_scoring_service.py.

# ── SOLIDEZ FINANCIERA (5 indicators) ───────────────────────────


def calc_solvencia(d) -> IndicatorResult:
    """Capital Adequacy Ratio: patrimonio_tecnico / (APR + contingentes + riesgo_mercado)."""
    denom = float(d.apr or 0) + float(d.contingentes or 0) + float(d.riesgo_mercado or 0)
    raw = _safe_div(d.patrimonio_tecnico, denom) * 100
    score = _clamp(min(100, (raw / 15) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_tier1_ratio(d) -> IndicatorResult:
    """Tier 1 Capital Ratio: capital_primario / APR."""
    raw = _safe_div(d.capital_primario, d.apr) * 100
    score = _clamp(min(100, ((raw - 4.5) / 4) * 100)) if raw >= 4.5 else 0
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_leverage(d) -> IndicatorResult:
    """Leverage Ratio: capital_tier1 / exposicion_total."""
    raw = _safe_div(d.capital_tier1, d.exposicion_total) * 100
    score = _clamp(min(100, (raw / 6) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_cobertura_provisiones(d) -> IndicatorResult:
    """Provision Coverage: provisiones / cartera_vencida_90d."""
    raw = _safe_div(d.provisiones, d.cartera_vencida_90d) * 100
    score = _clamp(min(100, raw))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_patrimonio_activos(d) -> IndicatorResult:
    """Equity-to-Assets: patrimonio_tecnico / activos_totales."""
    raw = _safe_div(d.patrimonio_tecnico, d.activos_totales) * 100
    score = _clamp(min(100, (raw / 12) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


# ── CALIDAD DE ACTIVOS (7 + 1 composite = 8 indicators) ────────


def calc_morosidad(d) -> IndicatorResult:
    """NPL Ratio: cartera_vencida_90d / cartera_bruta (inverse: lower is better)."""
    raw = _safe_div(d.cartera_vencida_90d, d.cartera_bruta) * 100
    score = _clamp(max(0, 100 - raw * 10))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_pct_cartera_a(d) -> IndicatorResult:
    """Category-A Portfolio: cartera_categoria_a / cartera_total."""
    raw = _safe_div(d.cartera_categoria_a, d.cartera_total or d.cartera_bruta) * 100
    score = _clamp(min(100, (raw / 90) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_concentracion_top10(d) -> IndicatorResult:
    """Top-10 Concentration: suma_top10 / cartera_total (inverse)."""
    raw = _safe_div(d.suma_top10, d.cartera_total or d.cartera_bruta) * 100
    score = _clamp(max(0, 100 - (raw - 30) * 1.5))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_hhi_sectorial(d) -> IndicatorResult:
    """Sector HHI: normalized from raw HHI value."""
    raw = float(d.hhi_sectorial_raw or 0)
    if raw < 1500:
        score = 100.0
    elif raw <= 2500:
        score = 100 - ((raw - 1500) / 10)
    else:
        score = 0.0
    return {"raw": round(raw, 4), "score": round(_clamp(score), 2)}


def calc_castigos_pct(d) -> IndicatorResult:
    """Write-offs: castigos / cartera_bruta (inverse)."""
    raw = _safe_div(d.castigos, d.cartera_bruta) * 100
    score = _clamp(max(0, 100 - raw * 5))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_exposicion_re(d) -> IndicatorResult:
    """Real Estate Exposure: exposicion_re / cartera_total (centered at 40%)."""
    raw = _safe_div(d.exposicion_re, d.cartera_total or d.cartera_bruta) * 100
    score = _clamp(100 - abs(raw - 40) / 1.5)
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_migracion(d) -> IndicatorResult:
    """Portfolio Migration: change in category-A portfolio vs previous period."""
    if d.cartera_a_prev and float(d.cartera_a_prev) > 0:
        raw = ((float(d.cartera_categoria_a or 0) - float(d.cartera_a_prev))
               / float(d.cartera_a_prev)) * 100
    else:
        raw = 0.0
    score = _clamp(100 - min(100, abs(raw) * 5))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_composite_calidad(indicators: Dict[str, IndicatorResult]) -> IndicatorResult:
    """Weighted average of the 7 calidad-de-activos indicators."""
    calidad_keys = [
        "morosidad", "pct_cartera_a", "concentracion_top10",
        "hhi_sectorial", "castigos_pct", "exposicion_re", "migracion",
    ]
    scores = [indicators[k]["score"] for k in calidad_keys if k in indicators]
    avg = sum(scores) / len(scores) if scores else 0
    return {"raw": round(avg, 4), "score": round(avg, 2)}


# ── EFICIENCIA Y RENTABILIDAD (4 indicators) ───────────────────


def calc_roa(d) -> IndicatorResult:
    """Return on Assets: utilidad_neta / activos_promedio."""
    raw = _safe_div(d.utilidad_neta, d.activos_promedio) * 100
    score = _clamp(min(100, (raw / 1.5) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_roe(d) -> IndicatorResult:
    """Return on Equity: utilidad_neta / patrimonio_promedio."""
    raw = _safe_div(d.utilidad_neta, d.patrimonio_promedio) * 100
    score = _clamp(min(100, (raw / 15) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_margen_financiero(d) -> IndicatorResult:
    """Net Interest Margin: (ingresos - gastos financieros) / activos_productivos_avg."""
    neto = float(d.ingresos_financieros or 0) - float(d.gastos_financieros or 0)
    raw = _safe_div(neto, d.activos_productivos_avg) * 100
    score = _clamp(min(100, (raw / 6) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_cost_to_income(d) -> IndicatorResult:
    """Cost-to-Income: gastos_operacionales / ingresos_operacionales (inverse)."""
    raw = _safe_div(d.gastos_operacionales, d.ingresos_operacionales) * 100
    score = _clamp(max(0, 100 - raw))
    return {"raw": round(raw, 4), "score": round(score, 2)}


# ── LIQUIDEZ (3 indicators) ────────────────────────────────────


def calc_liquidez_inmediata(d) -> IndicatorResult:
    """Immediate Liquidity: caja_valores / pasivos_cp."""
    raw = _safe_div(d.caja_valores, d.pasivos_cp) * 100
    score = _clamp(min(100, (raw / 30) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_ltd(d) -> IndicatorResult:
    """Loan-to-Deposit with bell curve scoring (optimal at 80%, sigma=15)."""
    raw = _safe_div(d.cartera_neta, d.depositos_totales) * 100
    sigma = 15
    score = _clamp(100 - 2 * ((raw - 80) ** 2) / (sigma ** 2))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_liquidez_ajustada(d) -> IndicatorResult:
    """Adjusted Liquidity: activos_liquidos / pasivos_exigibles."""
    raw = _safe_div(d.activos_liquidos, d.pasivos_exigibles) * 100
    score = _clamp(min(100, (raw / 80) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


# ── DIVERSIFICACIÓN (1 indicator) ──────────────────────────────


def calc_hhi_ingresos(d) -> IndicatorResult:
    """Income HHI: normalized inverse HHI of income sources."""
    raw = float(d.hhi_ingresos_raw or 0)
    if raw < 3000:
        score = 100.0
    elif raw <= 5000:
        score = 100 - ((raw - 3000) / 20)
    else:
        score = 0.0
    return {"raw": round(raw, 4), "score": round(_clamp(score), 2)}


# ─── Dispatch table ─────────────────────────────────────────────

_INDICATOR_FUNCS = {
    # Solidez
    "solvencia": calc_solvencia,
    "tier1_ratio": calc_tier1_ratio,
    "leverage": calc_leverage,
    "cobertura_provisiones": calc_cobertura_provisiones,
    "patrimonio_activos": calc_patrimonio_activos,
    # Calidad (individual)
    "morosidad": calc_morosidad,
    "pct_cartera_a": calc_pct_cartera_a,
    "concentracion_top10": calc_concentracion_top10,
    "hhi_sectorial": calc_hhi_sectorial,
    "castigos_pct": calc_castigos_pct,
    "exposicion_re": calc_exposicion_re,
    "migracion": calc_migracion,
    # Eficiencia
    "roa": calc_roa,
    "roe": calc_roe,
    "margen_financiero": calc_margen_financiero,
    "cost_to_income": calc_cost_to_income,
    # Liquidez
    "liquidez_inmediata": calc_liquidez_inmediata,
    "ltd": calc_ltd,
    "liquidez_ajustada": calc_liquidez_ajustada,
    # Diversificación
    "hhi_ingresos": calc_hhi_ingresos,
}


# ─── Public API ─────────────────────────────────────────────────


def calculate_all_indicators(data) -> Dict[str, IndicatorResult]:
    """Calculate all 19 indicators (+ composite) from raw banking data.

    *data* can be any object whose attributes match the field names in
    ``BankingDataInput`` (SQLAlchemy model, dataclass, etc.).

    Returns ``{indicator_name: {"raw": float, "score": float}}``.
    """
    indicators: Dict[str, IndicatorResult] = {}

    for name, func in _INDICATOR_FUNCS.items():
        indicators[name] = func(data)

    # Composite calidad depends on the individual calidad indicators
    indicators["composite_calidad"] = calc_composite_calidad(indicators)

    return indicators


def calculate_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, float]:
    """Aggregate indicators into 5 weighted sub-component scores."""
    groups = {
        "solidez": SOLIDEZ_INDICATORS,
        "calidad": CALIDAD_INDICATORS,
        "eficiencia": EFICIENCIA_INDICATORS,
        "liquidez": LIQUIDEZ_INDICATORS,
        "diversificacion": DIVERSIFICACION_INDICATORS,
    }

    def _avg(keys: List[str]) -> float:
        vals = [indicators[k]["score"] for k in keys if k in indicators]
        return sum(vals) / len(vals) if vals else 0.0

    return {comp: round(_avg(keys), 2) for comp, keys in groups.items()}


def calculate_deterministic_score(sub_scores: Dict[str, float]) -> float:
    """Weighted-sum overall score from sub-component scores."""
    total = sum(sub_scores.get(k, 0) * w for k, w in SUB_COMPONENT_WEIGHTS.items())
    return round(_clamp(total), 2)


def run_scoring(data) -> Dict[str, Any]:
    """Full deterministic scoring pipeline (no DB, no ML).

    Returns a complete breakdown: indicators, sub-components, overall score,
    rating tier, and tier color.
    """
    indicators = calculate_all_indicators(data)
    sub_scores = calculate_sub_components(indicators)
    overall_score = calculate_deterministic_score(sub_scores)
    tier = map_rating_tier(overall_score)
    color = get_tier_color(tier)

    return {
        "overall_score": overall_score,
        "rating_tier": tier,
        "tier_color": color,
        "sub_components": sub_scores,
        "indicators": {
            name: {"raw": float(v["raw"]), "score": float(v["score"])}
            for name, v in indicators.items()
        },
        "model_type": "deterministic",
        "model_version": "1.0",
    }


def simulate_from_scores(modified_scores: Dict[str, float]) -> Dict[str, Any]:
    """Recalculate rating from manually modified indicator scores (0-100).

    Used by the iSRM interactive scenario modeler.  Accepts a flat dict of
    ``{indicator_key: score}`` and returns sub-component scores, overall score,
    rating tier, and color.
    """
    # Recompute composite_calidad from its components
    calidad_raw_keys = [
        "morosidad", "pct_cartera_a", "concentracion_top10",
        "hhi_sectorial", "castigos_pct", "exposicion_re", "migracion",
    ]
    present = [k for k in calidad_raw_keys if k in modified_scores]
    composite_calidad = sum(modified_scores[k] for k in present) / max(len(present), 1)
    modified_scores["composite_calidad"] = round(composite_calidad, 2)

    groups = {
        "solidez": SOLIDEZ_INDICATORS,
        "calidad": CALIDAD_INDICATORS,
        "eficiencia": EFICIENCIA_INDICATORS,
        "liquidez": LIQUIDEZ_INDICATORS,
        "diversificacion": DIVERSIFICACION_INDICATORS,
    }
    sub_components: Dict[str, float] = {}
    for comp, keys in groups.items():
        vals = [modified_scores.get(k, 0.0) for k in keys if k in modified_scores]
        sub_components[comp] = round(sum(vals) / len(vals), 2) if vals else 0.0

    overall = round(
        sum(sub_components.get(k, 0.0) * w for k, w in SUB_COMPONENT_WEIGHTS.items()), 2
    )
    tier = map_rating_tier(overall)
    color = get_tier_color(tier)

    return {
        "sub_components": sub_components,
        "overall_score": overall,
        "rating_tier": tier,
        "tier_color": color,
    }
