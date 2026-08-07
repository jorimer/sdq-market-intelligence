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
    get_sub_component_weights,
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


def _score_tramos(raw: float, lo: float, ref: float, hi: float) -> float:
    """Puntúa un indicador en dos tramos: ``lo``→0, **``ref``→50**, ``hi``→100.

    ``ref`` es el hecho económico del indicador — el mínimo regulatorio, o el punto donde
    las provisiones cubren la cartera vencida. Cumplirlo vale 50: ni "aprobado con lo justo
    = 100", ni "aprobado = reprobado".

    Reemplaza a las rectas del tipo ``min(100, raw / techo * 100)`` que tenían el techo
    apenas por encima del mínimo regulatorio y saturaban a casi todo el sistema. Medido en
    producción (2026-08-07, 46 entidades con dato): **96% de las entidades marcaba 100/100
    en tier1, leverage y cobertura de provisiones**, y 67% en solvencia. El sub-componente
    de mayor peso (solidez, 40%) no discriminaba: casi todas sacaban casi el máximo, y eso
    empujaba al 89% del sistema a una sola banda de Resiliencia.

    Los techos salen del percentil 90 observado, no de un número redondo: el objetivo es
    separar a las entidades bien capitalizadas de las MUY bien capitalizadas, que es
    justamente lo que un techo bajo vuelve imposible.
    """
    if raw <= lo:
        return 0.0
    if raw <= ref:
        return _clamp((raw - lo) / (ref - lo) * 50) if ref > lo else 50.0
    return _clamp(50 + (raw - ref) / (hi - ref) * 50) if hi > ref else 100.0


def _ttm_profit(d) -> Optional[float]:
    """Utilidad de los ÚLTIMOS 12 MESES, o ``None`` si no es computable.

    Reemplaza a la anualización por ``12/mes`` que se usaba antes. Ese factor asumía que
    todos los trimestres pesan igual, y el panel lo refuta: sobre 71 banco-años de 16 bancos
    múltiples (2021-2025) el PRIMER TRIMESTRE concentra una mediana de 9,9% de la utilidad
    anual —97% de los casos bajo el 20%— mientras Q2/Q3/Q4 aportan ~30% cada uno. Multiplicar
    ×4 un trimestre que vale 9,9% proyecta ~40% de la tasa anual real: BPD marcaba ROE 10,2%
    al Q1 contra 24,2% al cierre, con el score cayendo de 100 a 68 sin cambio de negocio.

    La ventana móvil la calcula ``scoring/ttm.attach_ttm`` (necesita DB) y llega como
    ``utilidad_ttm``. En un corte de DICIEMBRE el acumulado del ejercicio ya es la ventana de
    doce meses, así que se usa directo. Sin período conocido (muestras sintéticas y tests) se
    asume anual, que es el comportamiento histórico de esos contextos.
    """
    ttm = getattr(d, "utilidad_ttm", None)
    if ttm is not None:
        return float(ttm)
    month = getattr(getattr(d, "period_end", None), "month", None)
    if month in (None, 12):
        u = getattr(d, "utilidad_neta", None)
        return float(u) if u is not None else None
    return None  # corte intermedio sin historia → el indicador se declara NO disponible


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
    # Pre-computed SIB ratios (%, dimensionless). When present, the engine prefers
    # them over the absolute-input formula — avoids cross-endpoint unit mixing.
    solvencia_pct: Optional[float] = None
    tier1_pct: Optional[float] = None
    morosidad_pct: Optional[float] = None
    cartera_vigente_pct: Optional[float] = None
    cobertura_pct: Optional[float] = None
    margen_pct: Optional[float] = None
    cost_income_pct: Optional[float] = None
    # Cartera-quality ratios computed from a single SIB endpoint each (unit-safe).
    castigos_pct: Optional[float] = None
    exposicion_re_pct: Optional[float] = None


# ─── Indicator result type ──────────────────────────────────────

IndicatorResult = Dict[str, float]  # {"raw": float, "score": float}


# ─── Individual indicator calculations ──────────────────────────
# Each function receives a data object and returns {"raw", "score"}.
# The score is always in [0, 100].
# Formulas extracted EXACTLY from monolith banking_scoring_service.py.

# ── SOLIDEZ FINANCIERA (5 indicators) ───────────────────────────


def _pct(d, field):
    """Pre-computed SIB ratio (%) if present, else None."""
    v = getattr(d, field, None)
    return float(v) if v is not None else None


def _sib_ratio_positive(d, field):
    """Pre-computed SIB ratio (%) ONLY if it is a plausible positive value, else None.

    Capital-adequacy ratios (solvency, Tier-1) are positive by construction — a bank
    with negative core capital would be insolvent. The SIB feed has shipped a NEGATED
    value for some periods (e.g. tier1 ≈ -14% where the real ratio is ≈ +14%); a
    non-positive value is therefore spurious and the caller must fall back to the
    structural derivation (capital / APR). Never trust a sign-flipped source figure.
    """
    v = _pct(d, field)
    return v if (v is not None and v > 0) else None


def calc_solvencia(d) -> IndicatorResult:
    """Capital Adequacy Ratio. Prefers the SIB 'Índice de Solvencia' (%); falls
    back to patrimonio_tecnico / (APR + contingentes + riesgo_mercado)."""
    raw = _sib_ratio_positive(d, "solvencia_pct")
    if raw is None:
        denom = float(d.apr or 0) + float(d.contingentes or 0) + float(d.riesgo_mercado or 0)
        raw = _safe_div(d.patrimonio_tecnico, denom) * 100
    # ref = 10%: mínimo regulatorio de solvencia en RD (Reglamento de Normas Prudenciales).
    # hi = 31.3: percentil 90 del sistema. El techo anterior (15%) lo alcanzaba el 67%.
    score = _score_tramos(raw, lo=6.0, ref=10.0, hi=31.3)
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_tier1_ratio(d) -> IndicatorResult:
    """Tier 1 Capital Ratio. Prefers the SIB 'Índice de Solvencia de Capital
    Primario' (%); falls back to capital_primario / APR."""
    raw = _sib_ratio_positive(d, "tier1_pct")
    if raw is None:
        raw = _safe_div(d.capital_primario, d.apr) * 100
    # ref = 6%: Tier 1 mínimo de Basilea III. hi = 32.5: percentil 90 del sistema.
    # El techo anterior (8.5%) lo alcanzaba el 96% de las entidades.
    score = _score_tramos(raw, lo=3.6, ref=6.0, hi=32.5)
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_leverage(d) -> IndicatorResult:
    """Leverage Ratio: capital_tier1 / exposicion_total."""
    raw = _safe_div(d.capital_tier1, d.exposicion_total) * 100
    # ref = 3%: leverage ratio mínimo de Basilea III. hi = 30.2: percentil 90 del sistema.
    # El techo anterior (6%) lo alcanzaba el 96%.
    score = _score_tramos(raw, lo=1.8, ref=3.0, hi=30.2)
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_cobertura_provisiones(d) -> IndicatorResult:
    """Provision Coverage. Prefers the SIB 'Cobertura de Cartera Vencida >90' (%);
    falls back to provisiones / cartera_vencida_90d."""
    raw = _pct(d, "cobertura_pct")
    if raw is None:
        raw = _safe_div(d.provisiones, d.cartera_vencida_90d) * 100
    # ref = 100%: las provisiones cubren exactamente la cartera vencida >90d. hi = 243.8:
    # percentil 90. El techo anterior (100%) lo alcanzaba el 96% — cubrir la cartera es el
    # piso de lo esperable, no la excelencia.
    score = _score_tramos(raw, lo=60.0, ref=100.0, hi=243.8)
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_patrimonio_activos(d) -> IndicatorResult:
    """Equity-to-Assets: patrimonio_tecnico / activos_totales."""
    raw = _safe_div(d.patrimonio_tecnico, d.activos_totales) * 100
    # Sin mínimo regulatorio directo: ref = 8%, el percentil 10 del sistema, que funciona
    # como piso observado de capitalización. hi = 28.0: percentil 90. El techo anterior
    # (12%) lo alcanzaba el 70% de las entidades.
    score = _score_tramos(raw, lo=4.8, ref=8.0, hi=28.0)
    return {"raw": round(raw, 4), "score": round(score, 2)}


# ── CALIDAD DE ACTIVOS (7 + 1 composite = 8 indicators) ────────


def calc_morosidad(d) -> IndicatorResult:
    """NPL Ratio (inverse: lower is better). Prefers the SIB 'Índice de Morosidad
    mayor a 90 días' (%); falls back to cartera_vencida_90d / cartera_bruta."""
    raw = _pct(d, "morosidad_pct")
    if raw is None:
        raw = _safe_div(d.cartera_vencida_90d, d.cartera_bruta) * 100
    score = _clamp(max(0, 100 - raw * 10))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_pct_cartera_a(d) -> IndicatorResult:
    """Performing portfolio %. Prefers the SIB 'Cartera Vigente / Bruta' (%);
    falls back to cartera_categoria_a / cartera_total."""
    raw = _pct(d, "cartera_vigente_pct")
    if raw is None:
        raw = _safe_div(d.cartera_categoria_a, d.cartera_total or d.cartera_bruta) * 100
    score = _clamp(min(100, (raw / 90) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def concentracion_top10_pct(d) -> float:
    """Concentración top-10 (%) — DEFINICIÓN ÚNICA, compartida con Alerta Temprana.

    Existe como función pública porque el motor de alertas la recalculaba por su cuenta con
    OTRO denominador (``cartera_bruta`` en vez de ``cartera_total``), y el mismo informe
    mostraba dos valores para el mismo concepto y el mismo corte: 50,90% en Calidad de
    Activos y en la tabla de indicadores, 51,5% en Alerta Temprana. Para un comité que lee
    el PDF una vez, eso no se lee como diferencia de definición sino como dato inconsistente.

    No era un criterio metodológico distinto: era el mismo cálculo escrito dos veces. La
    cura es que exista una sola vez.
    """
    return _safe_div(d.suma_top10, d.cartera_total or d.cartera_bruta) * 100


def calc_concentracion_top10(d) -> IndicatorResult:
    """Top-10 Concentration: suma_top10 / cartera_total (inverse)."""
    raw = concentracion_top10_pct(d)
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
    """Write-offs (inverse). Prefers the SIB ratio castigos/carteraTotal (%) from
    indicadores/morosidad-estresada; falls back to castigos / cartera_bruta."""
    raw = _pct(d, "castigos_pct")
    if raw is None:
        raw = _safe_div(d.castigos, d.cartera_bruta) * 100
    score = _clamp(max(0, 100 - raw * 5))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_exposicion_re(d) -> IndicatorResult:
    """Real Estate Exposure (centered at 40%). Prefers the SIB ratio
    deuda-hipotecaria/deuda (%) from indicadores/riesgo-credito; falls back to
    exposicion_re / cartera_total."""
    raw = _pct(d, "exposicion_re_pct")
    if raw is None:
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
    """Return on Assets: utilidad de los ÚLTIMOS 12 MESES / activos_promedio."""
    ttm = _ttm_profit(d)
    if ttm is None:
        return {"raw": 0.0, "score": 0.0}   # `available=False` lo declara no disponible
    raw = _safe_div(ttm, d.activos_promedio) * 100
    score = _clamp(min(100, (raw / 1.5) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_roe(d) -> IndicatorResult:
    """Return on Equity: utilidad de los ÚLTIMOS 12 MESES / patrimonio_promedio."""
    ttm = _ttm_profit(d)
    if ttm is None:
        return {"raw": 0.0, "score": 0.0}   # `available=False` lo declara no disponible
    raw = _safe_div(ttm, d.patrimonio_promedio) * 100
    score = _clamp(min(100, (raw / 15) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_margen_financiero(d) -> IndicatorResult:
    """Net Interest Margin. Prefers the SIB 'Margen de Intermediación Neto' (%);
    falls back to (ingresos - gastos financieros) / activos_productivos_avg."""
    raw = _pct(d, "margen_pct")
    if raw is None:
        neto = float(d.ingresos_financieros or 0) - float(d.gastos_financieros or 0)
        raw = _safe_div(neto, d.activos_productivos_avg) * 100
    score = _clamp(min(100, (raw / 6) * 100))
    return {"raw": round(raw, 4), "score": round(score, 2)}


def calc_cost_to_income(d) -> IndicatorResult:
    """Cost-to-Income, Fitch-style: opex / pre-provision operating revenue, computed
    from the real income statement (gastos_operacionales / ingresos_operacionales).

    Calibrated to the DR system distribution (≈40% best decile → 100, ≈90% worst
    decile → 0, linear) instead of the old naive ``100 - raw``. The old curve scored
    the narrower SIB 'Gastos Op / Ingresos Op' ratio (~15-20pp higher than Fitch's
    definition), which pinned the whole system near 20 and drove an alarmist verdict.
    See docs/DEEP_DIVE_FITCH_PARITY.md."""
    raw = _safe_div(d.gastos_operacionales, d.ingresos_operacionales) * 100
    score = _clamp((90.0 - raw) / 0.50)
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
    """Income diversification (inverse HHI of income sources).

    Income has only ~4 source buckets, so the HHI floors around 2500–3000 even when
    well spread, and DR banking is interest-income-heavy (observed range across the
    universe ≈ 3400–8500, median ≈ 5400). The old 3000–5000 curve pegged ~2/3 of
    banks at 0 (no discrimination). Recalibrated to the real range: 100 at HHI ≤ 3000
    (well diversified for income), 0 at ≥ 9000 (near-single-source), linear between."""
    raw = float(d.hhi_ingresos_raw or 0)
    score = _clamp(100 * (9000 - raw) / 6000)
    return {"raw": round(raw, 4), "score": round(score, 2)}


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


# ─── Data integrity ─────────────────────────────────────────────
# Each indicator's required input fields. An indicator is only "available" when
# all of its inputs are present (not None). A missing input must NOT score as a
# perfect/zero value (e.g. morosidad with no NPL data scored 100 = false perfect).
# Unavailable indicators are excluded from the sub-component average, and
# sub-components with no available indicators are N/D and dropped from the overall
# score (weights renormalize over what's actually measured). This keeps the rating
# auditable: every number traces to real data.

INDICATOR_REQUIRES: Dict[str, List[str]] = {
    "solvencia": ["patrimonio_tecnico", "apr"],
    "tier1_ratio": ["capital_primario", "apr"],
    "leverage": ["capital_tier1", "exposicion_total"],
    "cobertura_provisiones": ["provisiones", "cartera_vencida_90d"],
    "patrimonio_activos": ["patrimonio_tecnico", "activos_totales"],
    "morosidad": ["cartera_vencida_90d", "cartera_bruta"],
    "pct_cartera_a": ["cartera_categoria_a"],
    "concentracion_top10": ["suma_top10"],
    "hhi_sectorial": ["hhi_sectorial_raw"],
    "castigos_pct": ["castigos"],
    "exposicion_re": ["exposicion_re"],
    "migracion": ["cartera_a_prev", "cartera_categoria_a"],
    "roa": ["utilidad_neta", "activos_promedio"],
    "roe": ["utilidad_neta", "patrimonio_promedio"],
    "margen_financiero": ["ingresos_financieros", "gastos_financieros", "activos_productivos_avg"],
    "cost_to_income": ["gastos_operacionales", "ingresos_operacionales"],
    "liquidez_inmediata": ["caja_valores", "pasivos_cp"],
    "ltd": ["cartera_neta", "depositos_totales"],
    "liquidez_ajustada": ["activos_liquidos", "pasivos_exigibles"],
    "hhi_ingresos": ["hhi_ingresos_raw"],
}

_CALIDAD_COMPONENT_KEYS = [
    "morosidad", "pct_cartera_a", "concentracion_top10",
    "hhi_sectorial", "castigos_pct", "exposicion_re", "migracion",
]

# Indicators that can be satisfied by a pre-computed SIB ratio field (preferred)
# in addition to their absolute-input formula.
INDICATOR_PCT_FIELD = {
    "solvencia": "solvencia_pct",
    "tier1_ratio": "tier1_pct",
    "morosidad": "morosidad_pct",
    "pct_cartera_a": "cartera_vigente_pct",
    "cobertura_provisiones": "cobertura_pct",
    "margen_financiero": "margen_pct",
    # cost_to_income intentionally omitted: it must be computed from the real income
    # statement (Fitch-style), NOT lifted from the narrower SIB pre-computed ratio.
    # See calc_cost_to_income and docs/DEEP_DIVE_FITCH_PARITY.md.
    "castigos_pct": "castigos_pct",
    "exposicion_re": "exposicion_re_pct",
}


# Denominador de cada ratio. Un denominador en CERO no da un ratio de cero: da un ratio
# indefinido, y el indicador debe declararse no disponible en vez de puntuar 0.
#
# `_safe_div` devuelve su default (0.0) cuando el denominador es 0 o None, así que la
# ausencia de dato terminaba puntuando como el peor valor posible. Estaba enmascarado
# mientras los demás indicadores saturaban en 100 y compensaban el hueco; al quitar la
# saturación quedó a la vista. Casos medidos en producción (2026-08-07): Citibank —una
# sucursal SIN cartera vencida— puntuaba 0 en cobertura de provisiones y perdía 16 puntos
# de rating por no tener mora; Banco Empire puntuaba 0 en solvencia, tier1 y leverage por
# falta de datos, no por estar descapitalizado.
INDICATOR_DENOMINATOR: Dict[str, str] = {
    "solvencia": "apr",
    "tier1_ratio": "apr",
    "leverage": "exposicion_total",
    "cobertura_provisiones": "cartera_vencida_90d",
    "patrimonio_activos": "activos_totales",
    "morosidad": "cartera_bruta",
}


def _indicator_available(data, name: str) -> bool:
    """True when the indicator can be computed — either from its pre-computed SIB
    ratio field, or from all of its required absolute inputs (not None)."""
    # ROA/ROE se miden sobre la ventana móvil de 12 meses: sin ella se DECLARAN no
    # disponibles (decisión del dueño), nunca se cae al acumulado anualizado — un número
    # calculado sobre un supuesto refutado es peor que un hueco declarado.
    if name in ("roa", "roe") and _ttm_profit(data) is None:
        return False
    pf = INDICATOR_PCT_FIELD.get(name)
    if pf is not None and getattr(data, pf, None) is not None:
        return True
    if not all(getattr(data, f, None) is not None for f in INDICATOR_REQUIRES.get(name, [])):
        return False
    # Denominador en cero → ratio indefinido, no ratio cero. Ver INDICATOR_DENOMINATOR.
    den = INDICATOR_DENOMINATOR.get(name)
    if den is not None:
        v = getattr(data, den, None)
        if v is None or float(v) == 0:
            return False
    return True


# ─── Public API ─────────────────────────────────────────────────


def calculate_all_indicators(data) -> Dict[str, IndicatorResult]:
    """Calculate all 19 indicators (+ composite) from raw banking data.

    Each result carries an ``available`` flag (False when its inputs are missing).
    *data* can be any object whose attributes match ``BankingDataInput``.
    """
    indicators: Dict[str, IndicatorResult] = {}

    for name, func in _INDICATOR_FUNCS.items():
        res = dict(func(data))
        res["available"] = _indicator_available(data, name)
        indicators[name] = res

    # Composite calidad = mean of the AVAILABLE calidad components (not faked).
    avail = [indicators[k]["score"] for k in _CALIDAD_COMPONENT_KEYS if indicators[k]["available"]]
    if avail:
        v = round(sum(avail) / len(avail), 2)
        indicators["composite_calidad"] = {"raw": v, "score": v, "available": True}
    else:
        indicators["composite_calidad"] = {"raw": 0.0, "score": 0.0, "available": False}

    return indicators


def calculate_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, Optional[float]]:
    """Aggregate indicators into 5 sub-component scores, averaging only the
    AVAILABLE indicators. A sub-component with no available indicator is ``None``
    (N/D) so the overall score can renormalize instead of crediting fake data.
    """
    groups = {
        "solidez": SOLIDEZ_INDICATORS,
        "calidad": CALIDAD_INDICATORS,
        "eficiencia": EFICIENCIA_INDICATORS,
        "liquidez": LIQUIDEZ_INDICATORS,
        "diversificacion": DIVERSIFICACION_INDICATORS,
    }

    def _avg(keys: List[str]) -> Optional[float]:
        vals = [
            indicators[k]["score"]
            for k in keys
            if k in indicators and indicators[k].get("available", True)
        ]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {comp: _avg(keys) for comp, keys in groups.items()}


def calculate_deterministic_score(sub_scores: Dict[str, Optional[float]], weights: Dict[str, float] = None) -> float:
    """Weighted-sum overall score from sub-component scores.

    N/D sub-components (``None``) are excluded and the remaining weights are
    renormalized, so the overall score reflects only what was actually measured
    (never credits missing data). *weights* defaults to the base profile.
    """
    weights = weights or SUB_COMPONENT_WEIGHTS
    present = {k: v for k, v in sub_scores.items() if v is not None and k in weights}
    total_w = sum(weights[k] for k in present)
    if total_w <= 0:
        return 0.0
    total = sum(present[k] * weights[k] for k in present) / total_w
    return round(_clamp(total), 2)


def run_scoring(data, entity_type=None) -> Dict[str, Any]:
    """Full deterministic scoring pipeline (no DB, no ML).

    *entity_type* selects the weight profile (banca_multiple, aap,
    banco_ahorro_credito, corporacion_credito, cambiaria, fiduciaria); unknown
    types fall back to the base weights.  Returns a complete breakdown.
    """
    weights = get_sub_component_weights(entity_type)
    if entity_type == "cambiaria":
        # FX/remittance agents have no credit book — use the dedicated indicator
        # set (same 5 sub-components, different inputs/thresholds).
        from modules.banking_score.scoring.cambiaria import (
            calculate_cambiaria_indicators,
            calculate_cambiaria_sub_components,
        )
        indicators = calculate_cambiaria_indicators(data)
        sub_scores = calculate_cambiaria_sub_components(indicators)
    elif entity_type == "fiduciaria":
        # Trust managers — no credit book; fee-based service company indicators
        # from the audited annual statements (same 5 sub-components).
        from modules.banking_score.scoring.fiduciaria import (
            calculate_fiduciaria_indicators,
            calculate_fiduciaria_sub_components,
        )
        indicators = calculate_fiduciaria_indicators(data)
        sub_scores = calculate_fiduciaria_sub_components(indicators)
    else:
        indicators = calculate_all_indicators(data)
        sub_scores = calculate_sub_components(indicators)
    overall_score = calculate_deterministic_score(sub_scores, weights)
    tier = map_rating_tier(overall_score)
    color = get_tier_color(tier)

    return {
        "overall_score": overall_score,
        "rating_tier": tier,
        "tier_color": color,
        "sub_components": sub_scores,
        "entity_type": entity_type,
        "weight_profile": weights,
        "indicators": {
            name: {
                "raw": float(v["raw"]) if v.get("raw") is not None else None,
                "score": float(v["score"]) if v.get("score") is not None else None,
                "available": v.get("available", True),
            }
            for name, v in indicators.items()
        },
        "model_type": "deterministic",
        # 1.2 — recalibración de los 5 indicadores de solidez a curvas de dos tramos con la
        # referencia regulatoria en 50 (antes saturaban al 96% del sistema), y denominador
        # cero tratado como indicador NO disponible en vez de score 0.
        "model_version": "1.2",
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
