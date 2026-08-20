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


# ─── Cambiaria indicators (raw + 0..100 score) ──────────────────

def _capitalizacion(d) -> IndicatorResult:
    # Patrimonio / Activos — FX agents are equity-funded; higher is sounder.
    # Calibrado contra el panel: p10 40.6 · mediana 91.1 · p90 99.8. El techo anterior (30%)
    # lo superaba casi todo el panel — las EIC se financian con capital propio, así que un
    # 30% de capitalización no es excelencia, es el piso del negocio.
    raw = _safe_div(_g(d, "patrimonio_tecnico"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 40.6, 99.8), 2)}


def _apalancamiento(d) -> IndicatorResult:
    """Pasivos / Patrimonio — menos es más sólido.

    Calibrado contra el panel: p10 0.00 · mediana 0.09 · p90 1.13. El umbral anterior (4.0)
    lo cumplían todas con enorme margen —una EIC casi no toma pasivos— así que 18 de 42
    marcaban 100 y el indicador no separaba a nadie.
    """
    patrimonio = _g(d, "patrimonio_tecnico")
    raw = _safe_div(_g(d, "pasivos_exigibles"), patrimonio)
    # Patrimonio no positivo: el ratio sale NEGATIVO y, como la escala es invertida, el clamp
    # lo mandaba al techo — una entidad insolvente sacaba 100/100. Ver `guards`.
    if not patrimonio_es_positivo(patrimonio):
        return peor_estado_prudencial(raw)
    return {"raw": round(raw, 4), "score": round(_lin(raw, 1.13, 0.0), 2)}


def _calidad_activos(d) -> IndicatorResult:
    # Activos líquidos / Activos — productive/liquid vs immobilized assets.
    # Calibrado contra las 42 EIC del panel (2026-08-07): p10 46.5 · mediana 90.5 · p90 99.2.
    # El techo anterior (70%) lo superaba el 71% de las entidades — un agente de cambio sano
    # tiene casi todo su activo líquido, así que 70 no separaba a nadie.
    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, 46.5, 99.2), 2)}


def _exposicion_credito(d) -> IndicatorResult:
    """Cartera / Activos — riesgo extra por un libro de crédito fuera de misión.

    ⚠️ En el panel actual este indicador es una CONSTANTE: las 42 EIC tienen 0% de cartera
    —no otorgan crédito, por definición del negocio— así que todas sacaban el mismo 100 y el
    indicador no aportaba información, solo empujaba el sub-componente de calidad hacia
    arriba. Un valor idéntico para todo el panel no discrimina; se declara NO DISPONIBLE.

    No se elimina: si una EIC llegara a tener cartera, el indicador vuelve a informar y el
    motor lo incluye solo.
    """
    raw = _safe_div(_g(d, "cartera_bruta"), _g(d, "activos_totales")) * 100
    if raw <= 0:
        return {"raw": 0.0, "score": 0.0, "available": False}
    return {"raw": round(raw, 4), "score": round(_lin(raw, 80, 10), 2)}


# ⚠️ Rentabilidad de una EIC: NO hay ancla económica externa.
#
# A diferencia de la solvencia (mínimo regulatorio) o del combined ratio en seguros
# (breakeven), no existe un "ROE correcto" para un agente de cambio. Y su ROE es
# estructuralmente bajo por una razón que NO es ineficiencia: están sobrecapitalizadas
# —mediana de patrimonio/activos 91%— y el patrimonio grande deprime el ROE de forma
# mecánica. Lo mismo que las hace puntuar alto en solidez las hace puntuar bajo en
# rentabilidad.
#
# Los anclajes salen de la distribución observada del panel (p10 → p90), que es lo único
# defendible cuando no hay referencia externa. El umbral anterior de ROE (0 → 18%) era el de
# un banco apalancado: con una mediana de 2.66%, mandaba a la mitad del sector a ~15 puntos.
def _roa(d) -> IndicatorResult:
    raw = _safe_div(_g(d, "utilidad_neta"), _g(d, "activos_totales")) * 100
    return {"raw": round(raw, 4), "score": round(_lin(raw, -0.85, 8.52), 2)}


def _roe(d) -> IndicatorResult:
    patrimonio = _g(d, "patrimonio_tecnico")
    raw = _safe_div(_g(d, "utilidad_neta"), patrimonio) * 100
    # Con patrimonio negativo el ROE cambia de SIGNO: una pérdida se lee como rentabilidad.
    # No es el peor valor, es un número que miente → se declara no disponible.
    if not patrimonio_es_positivo(patrimonio):
        return no_interpretable(raw)
    return {"raw": round(raw, 4), "score": round(_lin(raw, -0.86, 13.60), 2)}


def _cobertura_liquida(d) -> IndicatorResult:
    """Activos líquidos / Pasivos exigibles — capacidad de operar y liquidar.

    En ESCALA LOGARÍTMICA. El ratio explota cuando los pasivos exigibles son mínimos, que es
    lo normal en un agente de cambio: el panel va de 94% a **34.284%**, tres órdenes de
    magnitud. En escala lineal, el techo anterior de 120% lo superaba el 86% de las entidades
    y las diferencias entre las que cubren 200% y 30.000% desaparecían por igual.

    Anclajes en los percentiles observados: p10 93.8 → p90 34.283,6.
    """
    import math

    raw = _safe_div(_g(d, "activos_liquidos"), _g(d, "pasivos_exigibles")) * 100
    if raw <= 0:
        return {"raw": 0.0, "score": 0.0, "available": False}
    lg = math.log10(raw)
    return {"raw": round(raw, 4),
            "score": round(_lin(lg, math.log10(93.8), math.log10(34283.6)), 2)}


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


def calculate_cambiaria_sub_components(indicators: Dict[str, IndicatorResult]) -> Dict[str, Any]:
    """Promedia solo los indicadores DISPONIBLES de cada sub-componente.

    Dos correcciones sobre la versión anterior:

    * **Respeta ``available``.** Un indicador marcado como no disponible —``exposicion_credito``
      cuando la EIC no tiene cartera, que es siempre— se excluía del flag pero se seguía
      promediando, así que su 100 constante empujaba el sub-componente hacia arriba sin
      informar nada.
    * **Sin indicadores disponibles → ``None``, no ``0.0``.** Un sub-componente sin datos
      puntuaba como el PEOR valor posible en vez de declararse ausente, y
      ``calculate_deterministic_score`` —que sí excluye los ``None`` y renormaliza— nunca
      llegaba a verlo. Mismo defecto que el de ``_safe_div`` en el motor de banca.
    """
    sub: Dict[str, Any] = {}
    for comp, funcs in _SUB.items():
        scores = [indicators[_NAMES[fn]]["score"] for fn in funcs
                  if _NAMES[fn] in indicators and indicators[_NAMES[fn]].get("available", True)]
        sub[comp] = round(sum(scores) / len(scores), 2) if scores else None
    return sub
