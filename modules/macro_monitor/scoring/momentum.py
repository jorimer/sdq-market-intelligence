"""Momentum scoring for macro time series (Eje 2).

Doctrine (§4): *signal of inflection > level*; *momentum > absolute level*.
We measure change and acceleration on a single series, with an uncertainty band
and a probabilistic continuity read (Tetlock) — never a dry point estimate.

Pure functions over ``[(period, value)]``; gaps (``None``) are skipped, never
interpolated.  Periods are assumed chronologically sortable as strings
("2025", "2025-Q1", "2025-01").
"""
import statistics
from typing import Dict, List, Optional, Tuple

from shared.data.series_nature import CHANGE_UNIT, RATE, UNKNOWN

Observation = Tuple[str, Optional[float]]

# How many recent changes define "recent" for volatility/continuity.
_RECENT_WINDOW = 4


def _trend(change: Optional[float], acceleration: Optional[float]) -> str:
    if change is None:
        return "insuficiente"
    if acceleration is None:
        return "estable"
    if acceleration > 0:
        return "acelerando"
    if acceleration < 0:
        return "desacelerando"
    return "estable"


def _continuity_prob(changes: List[float]) -> Optional[float]:
    """Fraction of recent changes sharing the latest change's sign (0.5 if flat)."""
    if not changes:
        return None
    latest = changes[-1]
    if latest == 0:
        return 0.5
    window = changes[-_RECENT_WINDOW:]
    same = sum(1 for c in window if (c > 0) == (latest > 0))
    return round(same / len(window), 2)


def _percent_change(change: float, prev: float, values: List[float],
                    nature: str) -> Tuple[Optional[float], Optional[str]]:
    """Variación porcentual SOLO donde significa algo. Devuelve ``(valor, razón)``.

    Las tres condiciones que la invalidan son distintas entre sí y merecen razones
    distintas: el cliente que recibe ``None`` tiene que poder saber si la serie no admite
    porcentajes por naturaleza, o si esta observación en particular lo hace insensato."""
    if nature == RATE:
        return None, ("serie ya expresada en porcentaje: su variación se mide en puntos "
                      "porcentuales (campo `change`), no en porcentaje sobre porcentaje")
    if nature == UNKNOWN:
        return None, ("naturaleza de la serie no declarada: no se elige una "
                      "transformación sin saber qué mide")
    if prev == 0:
        return None, "el período previo vale cero: la variación porcentual no está definida"
    # Cambio de signo: el cociente da un número, pero no es una variación interpretable.
    if (prev < 0) != (prev + change < 0):
        return None, ("la serie cruza el cero entre ambos períodos: el signo cambia y la "
                      "variación porcentual pierde significado")
    # Base despreciable frente a la escala de la serie: el porcentaje explota.
    escala = max((abs(v) for v in values), default=0.0)
    if escala > 0 and abs(prev) < 0.01 * escala:
        return None, ("el período previo es despreciable frente a la escala de la serie: "
                      "el porcentaje resultante no es informativo")
    return round(change / abs(prev) * 100, 2), None


def compute_series_momentum(observations: List[Observation],
                            nature: str = UNKNOWN) -> Dict:
    """Métricas de momentum de una serie, SEGÚN SU NATURALEZA estadística.

    ``nature`` decide qué transformación es válida — no es un adorno, es la corrección de
    un error de categoría que afectaba al 37% del catálogo:

    * ``rate`` — la serie YA es un porcentaje. Su variación se mide en PUNTOS
      PORCENTUALES y ``pct_change`` queda en ``None``: la inflación que pasa de 4.23% a
      5.35% subió **1.12 puntos**, y decir "+26.48%" se lee como que subió 26%.
    * ``index`` / ``flow`` — la variación porcentual es la lectura correcta… salvo que la
      base sea despreciable o el signo cambie (ver abajo).
    * ``stock`` — la lectura natural es el cambio de NIVEL. El porcentaje solo se emite si
      el signo es estable: una posición neta que cruza el cero no admite variación
      porcentual, por más que la división dé un número.
    * ``unknown`` — no se computa porcentaje. No saber qué se mide no autoriza a elegir
      una transformación al azar.

    Cuando el porcentaje no aplica, ``pct_change`` va en ``None`` y ``pct_change_reason``
    dice por qué. Un ``None`` con razón es dato; un número sin sentido es ruido con
    apariencia de dato.
    """
    # Drop gaps; keep order.
    clean = [(p, float(v)) for p, v in observations if v is not None]

    base = {
        "nature": nature,
        "change_unit": CHANGE_UNIT.get(nature),
        "pct_change_reason": None,
        "n_obs": len(clean),
        "latest_period": clean[-1][0] if clean else None,
        "latest_value": clean[-1][1] if clean else None,
        "change": None,
        "pct_change": None,
        "acceleration": None,
        "trend": "insuficiente",
        "volatility": None,
        "uncertainty_band": None,
        "continuity_prob": None,
    }
    if len(clean) < 2:
        return base

    values = [v for _, v in clean]
    changes = [round(values[i] - values[i - 1], 4) for i in range(1, len(values))]

    change = changes[-1]
    prev = values[-2]
    pct_change, pct_reason = _percent_change(change, prev, values, nature)
    acceleration = round(changes[-1] - changes[-2], 4) if len(changes) >= 2 else None

    recent = changes[-_RECENT_WINDOW:]
    volatility = round(statistics.pstdev(recent), 4) if len(recent) >= 2 else None

    latest_value = values[-1]
    projected = latest_value + change
    uncertainty_band = (
        [round(projected - volatility, 4), round(projected + volatility, 4)]
        if volatility is not None else None
    )

    base.update(
        nature=nature,
        change_unit=CHANGE_UNIT.get(nature),
        change=change,
        pct_change=pct_change,
        pct_change_reason=pct_reason,
        acceleration=acceleration,
        trend=_trend(change, acceleration),
        volatility=volatility,
        uncertainty_band=uncertainty_band,
        continuity_prob=_continuity_prob(changes),
    )
    return base
