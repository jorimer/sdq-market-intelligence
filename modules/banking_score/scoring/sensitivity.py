"""Tabla de sensibilidades simétrica (Fase 4): qué sube y qué baja el score, con umbral.

Determinista, sin IA. Para la entidad del deep dive responde dos preguntas Fitch-grade:
- **Palancas al alza** — qué indicador, mejorando a qué UMBRAL en su valor crudo, sube el
  score global cuánto (la palanca de mayor retorno).
- **Riesgos a la baja** — qué indicador, deteriorándose a qué umbral, hace perder banda y
  cuánto cuesta al score global.

Dos piezas, ambas ancladas al motor real (no re-derivan la metodología):
1. **Umbral en valor crudo** — invierte la curva `score = f(raw)` de cada indicador
   (``_CURVES``, espejo de ``engine.py``). Un test round-trip fija el espejo al motor:
   si una curva se recalibra, el test falla. Para indicadores de óptimo (LtD, exposición
   inmobiliaria, migración) el umbral se expresa sobre el lado en que está la entidad.
2. **Impacto en el score global** — recomputa con ``calculate_sub_components`` +
   ``calculate_deterministic_score`` (pesos por tipo de entidad, renormalización N/D) sobre
   una copia de los indicadores con un score cambiado → delta exacto, no una aproximación.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

from modules.banking_score.scoring.engine import (
    calculate_deterministic_score, calculate_sub_components)
from modules.banking_score.scoring.indicator_detail import INDICATOR_META, _band
from modules.banking_score.scoring import hhi_estratos
from modules.banking_score.scoring.weights import get_sub_component_weights

# Fronteras de banda (score) — coinciden con _band(): fuerte≥85, adecuado≥70, moderado≥55.
_BAND_EDGES = (55.0, 70.0, 85.0)


class _Curve:
    """Inverso de la curva de un indicador: score→raw. ``direction`` = cómo lee el raw
    (higher/lower/target). ``to_raw(target, current)`` da el umbral crudo para *target*;
    para 'target' usa *current* para elegir el lado (óptimo de dos ramas)."""

    def __init__(self, direction: str, to_raw: Callable[..., float],
                 estratificada: bool = False):
        self.direction = direction
        self._to_raw = to_raw
        # Las curvas estratificadas necesitan el tipo de entidad para elegir sus anclas; el
        # resto lo ignora. Se declara acá para que `to_raw` no tenga que adivinar por firma.
        self.estratificada = estratificada

    def to_raw(self, target_score: float, current_raw: float,
               entity_type: Optional[str] = None) -> float:
        if self.estratificada:
            return self._to_raw(target_score, current_raw, entity_type)
        return self._to_raw(target_score, current_raw)


def _higher(k: float, offset: float = 0.0) -> _Curve:
    # score = min(100, (raw - offset) / k * 100)  →  raw = offset + score*k/100
    return _Curve("higher", lambda s, _cur: offset + s * k / 100.0)


def _tramos(lo: float, ref: float, hi: float) -> _Curve:
    """Inversa de ``engine._score_tramos``: dos tramos, ``ref`` en 50.

    Sin esta inversa las simulaciones de "¿qué necesito para subir de tier?" mentirían —
    devolverían el raw de una fórmula que el motor ya no usa. El test round-trip de
    ``test_sensitivity`` fija que ambas curvas coincidan.
    """
    def to_raw(s: float, _cur: float) -> float:
        return lo + (s / 50.0) * (ref - lo) if s <= 50 else ref + ((s - 50.0) / 50.0) * (hi - ref)
    return _Curve("higher", to_raw)


def _lower(to_raw: Callable[[float], float]) -> _Curve:
    return _Curve("lower", lambda s, _cur: to_raw(s))


def _target(to_raw_side: Callable[[float, float], float]) -> _Curve:
    return _Curve("target", to_raw_side)


# Espejo de las curvas de engine.py (fijado por test round-trip). composite_calidad no
# está: es derivado, no una palanca de entrada.
_CURVES: Dict[str, _Curve] = {
    # Solidez — higher is better, min(100, raw/K*100)
    # Solidez — curva de dos tramos con la referencia regulatoria en 50 (ver
    # engine._score_tramos). Los techos anteriores saturaban al 96% del sistema.
    "solvencia": _tramos(6.0, 10.0, 31.3),
    "tier1_ratio": _tramos(3.6, 6.0, 32.5),
    "leverage": _tramos(1.8, 3.0, 30.2),
    "cobertura_provisiones": _tramos(60.0, 100.0, 243.8),
    "patrimonio_activos": _tramos(4.8, 8.0, 28.0),
    # Calidad
    "morosidad": _lower(lambda s: (100.0 - s) / 10.0),
    "pct_cartera_a": _tramos(90.0, 94.0, 98.7),
    # sujeto-ok: es la CLAVE del indicador en la curva, no una porción servida
    "concentracion_top10": _lower(lambda s: (100.0 - s) * 57.0 / 100.0),
    # Estratificada: mismas anclas que `engine.calc_hhi_sectorial`, una sola fuente.
    "hhi_sectorial": _Curve("lower", lambda s, _cur, et: hhi_estratos.raw_de(s, et),
                            estratificada=True),
    "castigos_pct": _lower(lambda s: (100.0 - s) * 3.43 / 100.0),
    "exposicion_re": _target(
        lambda s, cur: 40.0 + (1.0 if cur >= 40.0 else -1.0) * (100.0 - s) * 1.5),
    "migracion": _target(
        lambda s, cur: (1.0 if cur >= 0.0 else -1.0) * (100.0 - s) / 5.0),
    # Eficiencia
    "roa": _tramos(0.0, 1.24, 3.46),
    "roe": _higher(15.0),
    "margen_financiero": _Curve("higher", lambda s, _c: 6.71 + s * (17.95 - 6.71) / 100.0),
    "cost_to_income": _lower(lambda s: 90.0 - 0.5 * s),
    # Liquidez
    "liquidez_inmediata": _higher(30.0),
    "ltd": _target(
        lambda s, cur: 80.0 + (1.0 if cur >= 80.0 else -1.0) * math.sqrt(max(0.0, (100.0 - s) * 112.5))),
    "liquidez_ajustada": _higher(80.0),
    # Diversificación
    # sujeto-ok: es la CLAVE del indicador en la curva, no una porción servida
    "hhi_ingresos": _lower(lambda s: 9000.0 - 60.0 * s),
}


def _next_edge_up(score: float) -> Optional[float]:
    """Frontera de banda inmediatamente superior al score (None si ya es fuerte)."""
    for e in _BAND_EDGES:
        if score < e:
            return e
    return None


def _next_edge_down(score: float) -> Optional[float]:
    """Frontera cuyo cruce a la baja hace perder banda (None si ya es la más baja)."""
    for e in reversed(_BAND_EDGES):
        if score >= e:
            return e
    return None


def _fmt_raw(key: str, raw: float) -> str:
    unit = (INDICATOR_META.get(key) or {}).get("unit", "%")
    if unit == "índice":
        return f"{raw:.0f}"
    if unit in ("veces", "ratio"):
        return f"{raw:.2f}"
    return f"{raw:.2f}%"


def _recompute_overall(indicators: Dict[str, Any], key: str, new_score: float,
                       weights: Dict[str, float]) -> float:
    """Overall recomputado con el score de *key* cambiado, reusando la agregación real
    (renormaliza N/D, recomputa composite_calidad, pesos por tipo)."""
    mod = {k: dict(v) for k, v in indicators.items() if isinstance(v, dict)}
    if key not in mod:
        return calculate_deterministic_score(calculate_sub_components(mod), weights)
    mod[key]["score"] = new_score
    mod[key]["available"] = True
    # composite_calidad = media de las 7 componentes de calidad disponibles.
    comp_keys = ["morosidad", "pct_cartera_a", "concentracion_top10", "hhi_sectorial",
                 "castigos_pct", "exposicion_re", "migracion"]
    avail = [mod[k]["score"] for k in comp_keys
             if k in mod and mod[k].get("available", True) and mod[k].get("score") is not None]
    if "composite_calidad" in mod and avail:
        v = round(sum(avail) / len(avail), 2)
        mod["composite_calidad"]["score"] = v
        mod["composite_calidad"]["available"] = True
    return calculate_deterministic_score(calculate_sub_components(mod), weights)


def nivel_de_referencia(clave: str, raw_actual: float,
                        entity_type: Optional[str] = None) -> Optional[float]:
    """El nivel al que *clave* puntúa 50 sobre 100 — su punto de referencia.

    **Por qué existe.** Un ratio no se puede leer sin su referencia. «Cobertura de 96,75 %»
    no dice nada hasta saber que 100 % es el nivel en que las provisiones cubren exactamente
    la cartera vencida. El modelo lo sabe —lo escribió solo— pero el contexto no se lo
    servía, así que la cifra llegaba SIN RESPALDO y el guard vetaba el informe entero. Dos
    Revisiones Anuales murieron así el 2026-08-27.

    No era un falso positivo del guard: era un HUECO en el dato. La doctrina del repo ya lo
    decía —«si no tenés la cifra que el modelo va a necesitar, pasásela igual con su nombre
    real: dejar el hueco es lo que lo llena mal»— y yo lo estaba tratando como un problema de
    lenguaje, parcheando el detector en vez de servir el número.

    **De dónde sale, y por qué no es una constante nueva.** Se COMPUTA invirtiendo la misma
    curva que usa el motor: en las de dos tramos, `ref` está fijada en el score 50 por
    construcción, así que `to_raw(50)` la devuelve exacta. Escribir «100.0» a mano acá sería
    la tercera copia del mismo número y la primera en desincronizarse.

    ``None`` si el indicador no tiene curva declarada (los derivados no la tienen).
    """
    curva = _CURVES.get(clave)
    if curva is None:
        return None
    try:
        return round(float(curva.to_raw(50.0, float(raw_actual), entity_type)), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def sensitivity_table(indicators: Dict[str, Any], entity_type: Optional[str] = None,
                      top: int = 3) -> Dict[str, Any]:
    """Tabla de sensibilidades simétrica para la entidad.

    Args:
        indicators: ``{key: {"raw","score","available"}}`` (scoring_result["indicators"]).
        entity_type: tipo de entidad → perfil de pesos (renormalización real).
        top: cuántas palancas / riesgos devolver por lado.

    Returns::

        {
          "baseline_overall": float,
          "palancas_alza":  [ {indicador,label,sub,raw_actual,score_actual,banda_actual,
                               umbral_raw,score_objetivo,banda_objetivo,delta_overall}, ...],
          "riesgos_baja":   [ {... delta_overall negativo ...}, ...],
        }

    'Palancas al alza' = mejorar el indicador a la banda siguiente (ordenadas por mayor
    ganancia de score global). 'Riesgos a la baja' = deteriorarlo hasta perder banda
    (ordenadas por mayor pérdida). Solo indicadores con curva invertible, disponibles y con
    frontera relevante.
    """
    weights = get_sub_component_weights(entity_type)
    base = calculate_deterministic_score(calculate_sub_components(indicators), weights)

    up: List[Dict[str, Any]] = []
    down: List[Dict[str, Any]] = []
    for key, d in indicators.items():
        if key == "composite_calidad" or key not in _CURVES:
            continue
        if not isinstance(d, dict) or d.get("available") is False:
            continue
        score = d.get("score")
        raw = d.get("raw")
        if score is None or not isinstance(raw, (int, float)):
            continue
        curve = _CURVES[key]
        meta = INDICATOR_META.get(key, {})
        label = meta.get("label", key)
        sub = meta.get("sub", "")

        edge_up = _next_edge_up(float(score))
        if edge_up is not None:
            target = edge_up + 0.01  # apenas dentro de la banda superior
            umbral = curve.to_raw(target, float(raw), entity_type)
            new_overall = _recompute_overall(indicators, key, target, weights)
            delta = round(new_overall - base, 2)
            if delta > 0.01:
                up.append({
                    "indicador": key, "label": label, "sub": sub,
                    "raw_actual": round(float(raw), 2), "score_actual": round(float(score), 1),
                    "banda_actual": _band(float(score)),
                    "umbral_raw": round(umbral, 2), "umbral_fmt": _fmt_raw(key, umbral),
                    "score_objetivo": round(target, 0), "banda_objetivo": _band(target),
                    "delta_overall": delta,
                })

        edge_down = _next_edge_down(float(score))
        if edge_down is not None and float(score) > edge_down - 0.01:
            target = edge_down - 0.01  # apenas debajo de la frontera (pierde banda)
            umbral = curve.to_raw(target, float(raw), entity_type)
            new_overall = _recompute_overall(indicators, key, target, weights)
            delta = round(new_overall - base, 2)
            if delta < -0.01:
                down.append({
                    "indicador": key, "label": label, "sub": sub,
                    "raw_actual": round(float(raw), 2), "score_actual": round(float(score), 1),
                    "banda_actual": _band(float(score)),
                    "umbral_raw": round(umbral, 2), "umbral_fmt": _fmt_raw(key, umbral),
                    "score_objetivo": round(target, 0), "banda_objetivo": _band(target),
                    "delta_overall": delta,
                })

    up.sort(key=lambda x: x["delta_overall"], reverse=True)
    down.sort(key=lambda x: x["delta_overall"])
    return {
        "baseline_overall": base,
        "palancas_alza": up[:top],
        "riesgos_baja": down[:top],
    }
