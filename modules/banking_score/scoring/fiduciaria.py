"""Scoring for fiduciarias (sociedades fiduciarias — fee-based trust managers).

Like cambiarias, these have NO credit book, no regulatory solvency (APR/RWA) and no
morosidad, so the 19 bank indicators don't apply. Their audited annual statements
(IFRS commercial format) give a full balance sheet + income statement. We map the
available figures onto the SAME 5 sub-components (persistence, weights and the output
contract are unchanged) with fiduciary-appropriate indicators.

Weight profile lives in ``weights.py`` ("fiduciaria": solidez 37 · calidad 22 ·
eficiencia 26 · liquidez 10 · diversificación 5, calibración v1.1 2026-06-11).
Thresholds here are a v1 and are
explicitly calibratable. Data is ANNUAL (period_type=annual).
"""
from typing import Dict

from modules.banking_score.scoring.engine import _clamp, _safe_div

IndicatorResult = Dict[str, float]


def _g(data, field: str, default: float = 0.0) -> float:
    v = getattr(data, field, default)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _lin(x: float, lo: float, hi: float) -> float:
    """Linear score: x<=lo → 0, x>=hi → 100 (or reversed if lo>hi)."""
    if hi == lo:
        return 50.0
    return _clamp((x - lo) / (hi - lo) * 100.0)


# ─── Fiduciaria indicators (raw + 0..100 score) ─────────────────

def _capitalizacion(d) -> IndicatorResult:
    # Patrimonio / Activos — fiduciaries are equity-funded service companies.
    raw = _safe_div(_g(d, "patrimonio_tecnico"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 15, 60), 2)}


def _apalancamiento(d) -> IndicatorResult:
    # Pasivos / Patrimonio — lower is sounder (reverse scale).
    raw = _safe_div(_g(d, "pasivos_exigibles"), _g(d, "patrimonio_tecnico"))
    return {"raw": round(raw, 4), "score": round(_lin(raw, 2.0, 0.0), 2)}


def _calidad_activos(d) -> IndicatorResult:
    # Activos líquidos / Activos — liquid/productive vs immobilized assets.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 15, 75), 2)}


def _cost_to_income(d) -> IndicatorResult:
    # Gastos operacionales / Ingresos — lower is more efficient (reverse scale).
    raw = _safe_div(_g(d, "gastos_operacionales"), _g(d, "ingresos_operacionales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 95, 45), 2)}


def _roa(d) -> IndicatorResult:
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.0, 15.0), 2)}


def _roe(d) -> IndicatorResult:
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "patrimonio_tecnico")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.0, 30.0), 2)}


def _cobertura_liquida(d) -> IndicatorResult:
    # Activos líquidos / Pasivos circulantes — capacity to meet near-term obligations.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "pasivos_cp")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 50, 200), 2)}


def _diversificacion(d) -> IndicatorResult:
    # HHI of income (comisiones fiduciarias vs otros), stored at ingestion in
    # hhi_ingresos_raw. Lower HHI = more diversified = higher score (reverse).
    hhi = _g(d, "hhi_ingresos_raw")
    if hhi <= 0:
        return {"raw": 0.0, "score": 0.0}
    return {"raw": round(hhi, 4), "score": round(_lin(hhi, 1.0, 0.3), 2)}


_SUB = {
    "solidez": [_capitalizacion, _apalancamiento],
    "calidad": [_calidad_activos],
    "eficiencia": [_cost_to_income, _roa, _roe],
    "liquidez": [_cobertura_liquida],
    "diversificacion": [_diversificacion],
}

_NAMES = {
    _capitalizacion: "capitalizacion", _apalancamiento: "apalancamiento",
    _calidad_activos: "calidad_activos", _cost_to_income: "cost_to_income",
    _roa: "roa", _roe: "roe", _cobertura_liquida: "cobertura_liquida",
    _diversificacion: "diversificacion_ingresos",
}


def calculate_fiduciaria_indicators(data) -> Dict[str, IndicatorResult]:
    out: Dict[str, IndicatorResult] = {}
    for funcs in _SUB.values():
        for fn in funcs:
            out[_NAMES[fn]] = fn(data)
    return out


def calculate_fiduciaria_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, float]:
    sub: Dict[str, float] = {}
    for comp, funcs in _SUB.items():
        scores = [indicators[_NAMES[fn]]["score"] for fn in funcs if _NAMES[fn] in indicators]
        sub[comp] = round(sum(scores) / len(scores), 2) if scores else 0.0
    return sub
