"""Posición de un sujeto dentro de su panel de comparables.

Casi todos los índices SDQ·MIP se sostienen sobre un panel (banca = entidades,
IRMP = países, ISA = AFP, IRC = países, IAI = sectores, IDM = regiones). La posición
relativa del sujeto —rango, percentil, distancia a la media— vivía solo dentro de la
prosa IA; este helper la expone como CAMPO ESTRUCTURADO uniforme para todas las
superficies de insight (patrón E2E-SYS1).

Determinista y sin dependencias de dominio: recibe el valor del sujeto y la lista de
valores del panel (incluyendo al sujeto), devuelve el bloque de posición.
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _distribution(values: List[float]) -> Dict[str, float]:
    mx, mn = max(values), min(values)
    return {
        "mean": round(sum(values) / len(values), 2),
        "max": round(mx, 2),
        "min": round(mn, 2),
        "spread": round(mx - mn, 2),
    }


def annotate_panel_position(
    subject_value: Optional[float],
    panel_values: List[float],
    *,
    higher_is_better: bool = True,
) -> Optional[Dict[str, object]]:
    """Posición del sujeto en el panel.

    ``panel_values`` es la lista completa de scores del panel (incluye al sujeto).
    Devuelve ``{rank, n, percentile, distribution}`` o ``None`` si no hay dato
    suficiente (sujeto None, o panel de <2 elementos: el rango no informa nada).

    - ``rank``: 1 = mejor posición (mayor score si ``higher_is_better``).
    - ``percentile``: 0-100, 100 = tope del panel; ``round(100*(n-rank)/(n-1))``.
    - ``distribution``: mean/max/min/spread del panel.

    Empates: comparten el mejor rango (rango = 1 + Nº estrictamente mejores).
    """
    if subject_value is None:
        return None
    vals = [v for v in panel_values if v is not None]
    n = len(vals)
    if n < 2:
        return None
    if higher_is_better:
        better = sum(1 for v in vals if v > subject_value)
    else:
        better = sum(1 for v in vals if v < subject_value)
    rank = better + 1
    percentile = round(100.0 * (n - rank) / (n - 1), 1)
    return {
        "rank": rank,
        "n": n,
        "percentile": percentile,
        "distribution": _distribution(vals),
    }
