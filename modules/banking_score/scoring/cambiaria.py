"""Scoring for intermediación cambiaria (EIC: agentes de cambio y remesas).

These entities have NO credit book, no regulatory solvency (APR/RWA) and no
morosidad — so the 19 bank indicators don't apply. The SIB EIC feed gives a full
balance sheet plus a summarized income statement (net result only). We map the
available figures onto the SAME 5 sub-components (so persistence, weights and the
output contract are unchanged) but with FX-intermediary-appropriate indicators.

Weight profile lives in ``weights.py`` ("cambiaria": solidez 35 · calidad 20 ·
eficiencia 20 · liquidez 20 · diversificación 5). Thresholds here are a v1 and
are explicitly calibratable.

NOTE (YTD): the SIB "Resultado del ejercicio" is year-to-date cumulative, so ROA/
ROE mix partial-year results across quarters — consistent with how the bank model
already treats utilidad_neta. Annualization is a future refinement.
"""
from typing import Any, Dict

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


# ─── Cambiaria indicators (raw + 0..100 score) ──────────────────

def _capitalizacion(d) -> IndicatorResult:
    # Patrimonio / Activos — FX agents are equity-funded; higher is sounder.
    raw = _safe_div(_g(d, "patrimonio_tecnico"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 5, 30), 2)}


def _apalancamiento(d) -> IndicatorResult:
    # Pasivos / Patrimonio — lower is sounder (reverse scale).
    raw = _safe_div(_g(d, "pasivos_exigibles"), _g(d, "patrimonio_tecnico"))
    return {"raw": round(raw, 4), "score": round(_lin(raw, 4.0, 0.0), 2)}


def _calidad_activos(d) -> IndicatorResult:
    # Activos líquidos / Activos — productive/liquid vs immobilized assets.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 10, 70), 2)}


def _exposicion_credito(d) -> IndicatorResult:
    # Cartera / Activos — an off-mission credit book is mild extra risk for an
    # FX agent; penalize gently, don't zero it out.
    raw = _safe_div(_g(d, "cartera_bruta"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 80, 10), 2)}


def _roa(d) -> IndicatorResult:
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.0, 4.0), 2)}


def _roe(d) -> IndicatorResult:
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "patrimonio_tecnico")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.0, 18.0), 2)}


def _cobertura_liquida(d) -> IndicatorResult:
    # Activos líquidos / Pasivos exigibles — capacity to operate/settle.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "pasivos_exigibles")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 20, 120), 2)}


def _diversificacion(d) -> IndicatorResult:
    # No income breakdown in the EIC feed → proxy: a balanced asset base (liquid
    # plus some other assets) beats an all-in-one-bucket balance. Neutral-ish.
    activos = _g(d, "activos_totales")
    liq = _safe_div(_g(d, "activos_liquidos"), activos) if activos else 0.0
    # Most diversified around a 50/50 liquid/other split.
    raw = 1 - abs(0.5 - liq) * 2  # 1 at 50%, 0 at 0% or 100%
    return {"raw": round(raw, 4), "score": round(_clamp(40 + raw * 50), 2)}


_SUB = {
    "solidez": [_capitalizacion, _apalancamiento],
    "calidad": [_calidad_activos, _exposicion_credito],
    "eficiencia": [_roa, _roe],
    "liquidez": [_cobertura_liquida],
    "diversificacion": [_diversificacion],
}

_NAMES = {
    _capitalizacion: "capitalizacion", _apalancamiento: "apalancamiento",
    _calidad_activos: "calidad_activos", _exposicion_credito: "exposicion_credito",
    _roa: "roa", _roe: "roe", _cobertura_liquida: "cobertura_liquida",
    _diversificacion: "diversificacion_ingresos",
}


def calculate_cambiaria_indicators(data) -> Dict[str, IndicatorResult]:
    out: Dict[str, IndicatorResult] = {}
    for funcs in _SUB.values():
        for fn in funcs:
            out[_NAMES[fn]] = fn(data)
    return out


def calculate_cambiaria_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, float]:
    sub: Dict[str, float] = {}
    for comp, funcs in _SUB.items():
        scores = [indicators[_NAMES[fn]]["score"] for fn in funcs if _NAMES[fn] in indicators]
        sub[comp] = round(sum(scores) / len(scores), 2) if scores else 0.0
    return sub
