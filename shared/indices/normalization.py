"""Regional min-max normalization for index variables.

A variable is normalized against the min/max of the regional/peer set for the
current period.  Variables flagged as risk-increasing are inverted so the
resulting 0-100 score is always directionally consistent (higher = better).

Promoted verbatim from ``macro_political_risk/scoring/normalization.py`` — this
is now the single implementation for every axis.
"""
from typing import Iterable, List, Tuple


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


# Panel mínimo para que los cuartiles signifiquen algo (≈3 observaciones por cuadrante).
# Debajo de esto la valla recorta dispersión legítima en vez de anomalías — ver docstring
# de ``robust_bounds``. Deja fuera del recorte a pensiones (7 AFP) y fiduciarias (4-5).
_MIN_N = 12


def _quantile(sorted_vals: List[float], q: float) -> float:
    """Cuantil por interpolación lineal sobre una lista YA ordenada."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (pos - lo) * (sorted_vals[hi] - sorted_vals[lo])


def robust_bounds(values: Iterable[float]) -> Tuple[float, float]:
    """Límites de peer min-max acotados por la valla de Tukey (Q1−1.5·IQR, Q3+1.5·IQR).

    El min-max crudo es frágil: **un solo outlier extremo comprime todo el resto del panel
    contra el borde opuesto**. Caso real (ISF 2024): Creciendo Seguros, con un combined ratio
    de 831%, estiraba el piso del margen técnico a −7.31 y empujaba a las otras 30
    aseguradoras a la banda alta, borrando la discriminación entre ellas.

    Se acota a la valla de Tukey —el criterio estándar de outlier— y nunca se expande más
    allá del dato real, así que en un panel sin outliers devuelve exactamente min/max y el
    comportamiento no cambia. Los valores fuera de la valla no se descartan: quedan del lado
    correcto del clamp (el peor sigue siendo el peor, con score 0).

    **Panel de menos de ``_MIN_N`` elementos → min/max crudos, sin recorte.** No es una
    salvaguarda menor: con pocos datos el IQR subestima la dispersión real y la valla recorta
    cola legítima como si fuera anomalía. Medido sobre las 7 AFP del ISA: la valla habría
    acotado los DOS extremos de ``rentabilidad`` (5.99-8.78 → 7.21-8.33), clampeando a la
    mejor y la peor en 100 y 0 y exagerando la diferencia entre ellas — justo lo contrario de
    lo que esta función existe para evitar. Con 33 aseguradoras el recorte sí aísla anomalías
    reales. Debajo del umbral, la falta de datos se declara, no se maquilla.

    >>> robust_bounds([1, 2, 3, 4])          # panel chico → min/max intactos
    (1.0, 4.0)
    >>> lo, hi = robust_bounds(list(range(1, 20)) + [500])
    >>> hi < 500                              # el outlier deja de estirar el techo
    True
    """
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return 0.0, 0.0
    if len(vals) < _MIN_N:
        return vals[0], vals[-1]
    q1, q3 = _quantile(vals, 0.25), _quantile(vals, 0.75)
    iqr = q3 - q1
    lo = max(vals[0], q1 - 1.5 * iqr)
    hi = min(vals[-1], q3 + 1.5 * iqr)
    return (vals[0], vals[-1]) if hi <= lo else (lo, hi)
