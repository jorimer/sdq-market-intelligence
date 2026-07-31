"""Attribution engine (S3) — was it the brand, or the market moving under it?

Two layers, deliberately kept apart because they rest on very different evidence:

1. **Category decomposition** — arithmetic. A brand's movement is split into the part the
   category's own movement explains and the residual. No modelling, no assumptions beyond
   the denominator itself.

2. **Cycle context** — qualitative. Whether the macro environment was demanding or helpful
   during the period, taken from the macro contract that ``macro_monitor`` publishes.

The second layer **never adjusts a number**. With a handful of waves there is no basis to
estimate how much a point of inflation moves a point of preference, and inventing that
elasticity would produce a figure far more confident than the evidence behind it. What it
does instead is state the environment the result was achieved in — which is what changes
whether a flat quarter reads as a failure or as holding ground against a headwind.

The environment index is a plain weighted balance of the contract's own direction and
magnitude fields. It is a summary of what the macro axis already published, not a new
model, and it degrades to "unknown" rather than to "neutral" when the contract is empty:
absent data must not masquerade as a benign environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

# Weights for the contract's declared magnitude.
_MAGNITUDE_WEIGHT = {"alto": 1.0, "moderado": 0.6, "bajo": 0.3}
_DIRECTION_SIGN = {"favorable": 1.0, "adverso": -1.0, "neutral": 0.0}

DEMANDING = "exigente"
FAVOURABLE = "favorable"
NEUTRAL = "neutral"
UNKNOWN = "desconocido"


@dataclass(frozen=True)
class EnvironmentReading:
    """How demanding the macro environment was during the period."""

    stance: str                  # exigente | favorable | neutral | desconocido
    index: Optional[float]       # [-1, 1]; negative = headwind
    adverse: int
    favourable: int
    neutral: int
    drivers: List[Dict[str, str]]
    note: str

    @property
    def known(self) -> bool:
        return self.stance != UNKNOWN


def read_environment(factors: Sequence[Dict[str, Any]]) -> EnvironmentReading:
    """Summarise the macro contract's factors into one stance for the period."""
    scored = [
        f for f in factors
        if f.get("direction") in _DIRECTION_SIGN and f.get("magnitude") in _MAGNITUDE_WEIGHT
    ]
    if not scored:
        return EnvironmentReading(
            UNKNOWN, None, 0, 0, 0, [],
            "Sin factores macro con lectura disponible: el entorno no se califica. "
            "El desempeño se lee en términos absolutos.",
        )

    total_weight = sum(_MAGNITUDE_WEIGHT[f["magnitude"]] for f in scored)
    signed = sum(
        _DIRECTION_SIGN[f["direction"]] * _MAGNITUDE_WEIGHT[f["magnitude"]] for f in scored
    )
    index = signed / total_weight if total_weight else 0.0

    adverse = sum(1 for f in scored if f["direction"] == "adverso")
    favourable = sum(1 for f in scored if f["direction"] == "favorable")
    neutral = sum(1 for f in scored if f["direction"] == "neutral")

    if index <= -0.25:
        stance = DEMANDING
    elif index >= 0.25:
        stance = FAVOURABLE
    else:
        stance = NEUTRAL

    drivers = [
        {"label": f.get("label", f.get("key", "")), "direction": f["direction"],
         "magnitude": f["magnitude"], "reading": f.get("reading", "")}
        for f in sorted(scored, key=lambda x: -_MAGNITUDE_WEIGHT[x["magnitude"]])[:4]
    ]
    return EnvironmentReading(
        stance, index, adverse, favourable, neutral, drivers,
        f"Balance de {len(scored)} factores macro ponderados por magnitud declarada: "
        f"{adverse} adverso(s), {favourable} favorable(s), {neutral} neutral(es).",
    )


@dataclass(frozen=True)
class IndicatorAttribution:
    """One indicator's movement, split and placed in its environment."""

    metric_code: str
    label: str
    wave_from: str
    wave_to: str
    delta: Optional[float]
    category_effect: Optional[float]
    brand_effect: Optional[float]
    verdict: str
    note: str


def decompose_indicator(
    metric_code: str,
    label: str,
    wave_from: str,
    wave_to: str,
    value_prev: Optional[float],
    value_curr: Optional[float],
    category_delta_pct: Optional[float],
    is_share_like: bool,
) -> IndicatorAttribution:
    """Split one indicator's movement between category and brand.

    ``is_share_like`` marks reach-type metrics that ride the category: only for those does
    a category move mechanically drag the brand's number. An attitude metric (preference,
    satisfaction) does not scale with category size, so attributing part of its movement to
    the category would be a category error dressed as arithmetic — those return the whole
    movement as the brand's, and say so.
    """
    if value_prev is None or value_curr is None:
        return IndicatorAttribution(
            metric_code, label, wave_from, wave_to, None, None, None,
            "sin_dato", "Falta una de las dos observaciones.",
        )

    delta = value_curr - value_prev

    if not is_share_like or category_delta_pct is None:
        return IndicatorAttribution(
            metric_code, label, wave_from, wave_to, delta, None, delta, "solo_marca",
            ("Indicador actitudinal: no escala con el tamaño de la categoría, "
             "de modo que el movimiento es íntegramente de la marca."
             if not is_share_like else
             "Sin variación de categoría disponible: el movimiento se atribuye a la marca."),
        )

    category_effect = value_prev * (category_delta_pct / 100.0)
    brand_effect = delta - category_effect

    if abs(delta) < 0.05:
        verdict = "sin_movimiento"
        note = "Sin movimiento apreciable."
    elif abs(brand_effect) >= abs(category_effect) * 2:
        verdict = "marca"
        note = "El movimiento es predominantemente de la marca."
    elif abs(category_effect) >= abs(brand_effect) * 2:
        verdict = "categoria"
        note = ("El movimiento se explica en su mayor parte por el tamaño de la categoría: "
                "corregir la marca sería corregir lo que no está roto.")
    else:
        verdict = "mixto"
        note = "Marca y categoría aportan de forma comparable."

    return IndicatorAttribution(
        metric_code, label, wave_from, wave_to, delta, category_effect, brand_effect,
        verdict, note,
    )


def cycle_reading(
    brand_effect: Optional[float], env: EnvironmentReading, higher_is_better: bool = True
) -> Dict[str, Any]:
    """Place the brand's own movement against the environment it was achieved in.

    Returns a qualitative reading only. The environment is never used to inflate or
    discount the figure — it changes the interpretation, not the number.
    """
    if brand_effect is None:
        return {"reading": "sin_dato",
                "text": "Sin movimiento atribuible calculable."}
    if not env.known:
        return {"reading": "sin_contexto", "text": env.note}

    improved = brand_effect > 0 if higher_is_better else brand_effect < 0
    flat = abs(brand_effect) < 0.5

    if flat:
        text = {
            DEMANDING: "La marca sostuvo su posición en un entorno exigente: "
                       "mantenerse tuvo mérito propio.",
            FAVOURABLE: "La marca se mantuvo plana en un entorno favorable: "
                        "no capitalizó el viento a favor.",
            NEUTRAL: "Sin movimiento propio, en un entorno sin sesgo claro.",
        }[env.stance]
        return {"reading": "sostuvo", "text": text}

    if improved:
        text = {
            DEMANDING: "La marca avanzó contra un entorno exigente: el avance es "
                       "atribuible a su propia gestión.",
            FAVOURABLE: "La marca avanzó en un entorno favorable: parte del avance "
                        "acompaña al ciclo.",
            NEUTRAL: "La marca avanzó en un entorno sin sesgo claro.",
        }[env.stance]
        return {"reading": "avanzo", "text": text}

    text = {
        DEMANDING: "La marca retrocedió en un entorno exigente: parte del retroceso "
                   "acompaña al ciclo, pero no lo explica por completo.",
        FAVOURABLE: "La marca retrocedió pese a un entorno favorable: el retroceso es "
                    "propio y merece atención.",
        NEUTRAL: "La marca retrocedió en un entorno sin sesgo claro.",
    }[env.stance]
    return {"reading": "retrocedio", "text": text}
