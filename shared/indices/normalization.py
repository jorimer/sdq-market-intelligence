"""Regional min-max normalization for index variables.

A variable is normalized against the min/max of the regional/peer set for the
current period.  Variables flagged as risk-increasing are inverted so the
resulting 0-100 score is always directionally consistent (higher = better).

Promoted verbatim from ``macro_political_risk/scoring/normalization.py`` — this
is now the single implementation for every axis.
"""
from typing import Iterable


def normalize_value(value: float, v_min: float, v_max: float, invert: bool = False) -> float:
    """Normalize *value* to [0, 100] given regional *v_min*/*v_max*.

    When *invert* is True (risk-increasing variable) the scale is reversed.
    When there is no spread (v_min == v_max) a neutral 50.0 is returned.

    >>> normalize_value(5, 0, 10)
    50.0
    >>> normalize_value(5, 0, 10, invert=True)
    50.0
    >>> normalize_value(10, 0, 10)
    100.0
    >>> normalize_value(10, 0, 10, invert=True)
    0.0
    """
    if v_max == v_min:
        return 50.0
    norm = 100.0 * (value - v_min) / (v_max - v_min)
    norm = max(0.0, min(100.0, norm))
    return round(100.0 - norm, 2) if invert else round(norm, 2)


def normalize_variable(value: float, regional_values: Iterable[float], invert: bool = False) -> float:
    """Normalize a value against the regional/peer distribution."""
    vals = [v for v in regional_values if v is not None]
    if not vals:
        return 50.0
    return normalize_value(value, min(vals), max(vals), invert)
