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
from typing import Any, Dict

from modules.banking_score.scoring.guards import (
    no_interpretable, patrimonio_es_positivo, peor_estado_prudencial,
)

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
    """Patrimonio / Activos — una fiduciaria es una sociedad de servicios fondeada con capital.

    Calibrado contra la SERIE 2020-2025 de las 4 entidades (24 observaciones, no 4): p10
    58.12 · mediana 76.39 · p90 87.42. El techo anterior (60%) lo superaba el 88% del panel
    histórico — con capital propio como única fuente de fondeo, 60% no es excelencia sino el
    piso del modelo de negocio.
    """
    raw = _safe_div(_g(d, "patrimonio_tecnico"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 58.12, 87.42), 2)}


def _apalancamiento(d) -> IndicatorResult:
    """Pasivos / Patrimonio — menos es más sólido. Serie 2020-2025: p10 0.14 · p90 0.72."""
    patrimonio = _g(d, "patrimonio_tecnico")
    raw = _safe_div(_g(d, "pasivos_exigibles"), patrimonio)
    # Mismo defecto que en cambiaria: escala invertida + patrimonio negativo = 100/100 para
    # una entidad insolvente. Ver `guards`.
    if not patrimonio_es_positivo(patrimonio):
        return peor_estado_prudencial(raw)
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.72, 0.14), 2)}


def _calidad_activos(d) -> IndicatorResult:
    # Activos líquidos / Activos — liquid/productive vs immobilized assets.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 15, 75), 2)}


def _cost_to_income(d) -> IndicatorResult:
    """Gastos operacionales / Ingresos — menos es más eficiente.

    Sin ingresos operacionales el ratio es INDEFINIDO, no cero. ``_safe_div`` devolvía 0.0 y
    eso se leía como "eficiencia perfecta": en la serie histórica, el 25% de las
    observaciones marcaba 0.00 de cost-to-income y sacaba 100 puntos. Mismo defecto que
    corrigió el motor de banca para los denominadores en cero.
    """
    ingresos = _g(d, "ingresos_operacionales")
    if not ingresos:
        return {"raw": 0.0, "score": 0.0, "available": False}
    raw = _safe_div(_g(d, "gastos_operacionales"), ingresos) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 95, 45), 2)}


def _roa(d) -> IndicatorResult:
    # Serie 2020-2025: p10 −8.54 · mediana 10.05 · p90 21.20. El techo anterior (15%) lo
    # alcanzaba un tercio del panel histórico.
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, -8.54, 21.20), 2)}


def _roe(d) -> IndicatorResult:
    patrimonio = _g(d, "patrimonio_tecnico")
    raw = _safe_div(_g(d, "utilidad_neta"), patrimonio) * 100
    if not patrimonio_es_positivo(patrimonio):
        return no_interpretable(raw)
    return {"raw": round(raw, 4), "score": round(_lin(raw, 0.0, 30.0), 2)}


def _cobertura_liquida(d) -> IndicatorResult:
    """Activos líquidos / Pasivos circulantes — capacidad de cubrir lo exigible a corto plazo.

    Sin pasivos circulantes la cobertura es INDEFINIDA (o infinita), nunca cero: una
    fiduciaria sin obligaciones de corto plazo no tiene un problema de liquidez, tiene una
    razón que no se puede calcular. ``_safe_div`` devolvía 0.0 y la penalizaba con 0 puntos.
    """
    pasivos = _g(d, "pasivos_cp")
    if not pasivos:
        return {"raw": 0.0, "score": 0.0, "available": False}
    raw = _safe_div(_g(d, "activos_liquidos"), pasivos) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 50, 200), 2)}


def _diversificacion(d) -> IndicatorResult:
    # HHI of income (comisiones fiduciarias vs otros), stored at ingestion in
    # hhi_ingresos_raw. Lower HHI = more diversified = higher score (reverse).
    hhi = _g(d, "hhi_ingresos_raw")
    if hhi <= 0:
        return {"raw": 0.0, "score": 0.0}
    # ⚠️ CONSTANTE ESTRUCTURAL, no un indicador. Las 4 fiduciarias son mono-línea —~100%
    # comisiones fiduciarias— así que el HHI da 1.0 en todas y el score 0 en todas.
    # `weights.py` ya lo documenta y por eso le recortó el peso (0.10 → 0.05), pero seguía
    # puntuando cero para el panel entero: no informaba nada y arrastraba el sub-componente
    # hacia abajo por igual. Se declara NO DISPONIBLE, como `exposicion_credito` en las EIC.
    # Si alguna diversificara sus ingresos, el indicador vuelve a informar y entra solo.
    if hhi >= 0.99:
        return {"raw": round(hhi, 4), "score": 0.0, "available": False}
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


def calculate_fiduciaria_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, Any]:
    """Promedia solo los indicadores DISPONIBLES. Sin ninguno → ``None``, no ``0.0``.

    Mismo defecto que tenía el agregador de EIC: ignoraba el flag ``available`` (así que
    declarar un indicador ausente no surtía efecto) y un sub-componente sin datos puntuaba
    como el PEOR valor posible en vez de declararse N/D, sin llegar nunca a
    ``calculate_deterministic_score``, que sí excluye los ``None`` y renormaliza.
    """
    sub: Dict[str, Any] = {}
    for comp, funcs in _SUB.items():
        scores = [indicators[_NAMES[fn]]["score"] for fn in funcs
                  if _NAMES[fn] in indicators and indicators[_NAMES[fn]].get("available", True)]
        sub[comp] = round(sum(scores) / len(scores), 2) if scores else None
    return sub
