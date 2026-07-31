"""Deflation engine — turning declared spend into constant pesos.

Trackers freeze their spend brackets in nominal terms and keep them for years, so "spend
held steady" can describe a real decline of several points and read as stability. This
engine puts the money in constant terms using the BCRD series.

It reads the series through ``shared.contracts.load_inflation_series`` — the cross-module
contract — so this module never imports ``macro_monitor``.

**Method.** The contract supplies year-over-year inflation by month, not a price level, so
the level is chained: each month contributes ``(1 + pi_t/100) ** (1/12)``. Chaining those
factors recovers the accumulated level and is exact when inflation is constant, converging
smoothly when it is not. Two properties matter more than the precision: it is reproducible
from a public series, and it degrades to *nothing* rather than to a guess — with no series,
the caller keeps the nominal figure and the report says it is nominal.

**Bracket midpoints.** Where spend arrives as ranges, the average is estimated from
midpoints. The open-ended top bracket has no midpoint, so it is a declared assumption and
the engine ships a sensitivity helper: any conclusion that does not survive the plausible
range of that assumption does not belong in the report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _months_between(start: date, end: date) -> List[str]:
    """Month keys strictly after ``start`` and up to ``end``."""
    out: List[str] = []
    y, m = start.year, start.month
    while (y, m) < (end.year, end.month):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        out.append(f"{y:04d}-{m:02d}")
    return out


@dataclass(frozen=True)
class DeflatorResult:
    factor: Optional[float]        # price level at `to` relative to `base` (1.0 = equal)
    coverage: float                # share of months with an observed rate [0,1]
    note: str

    @property
    def available(self) -> bool:
        return self.factor is not None


def price_level_factor(
    inflation_yoy: Dict[str, float], base: date, to: date
) -> DeflatorResult:
    """Accumulated price level between two dates, chained from year-over-year rates."""
    if to <= base:
        return DeflatorResult(1.0, 1.0, "Fecha base igual o posterior: factor 1,0.")

    months = _months_between(base, to)
    if not months:
        return DeflatorResult(1.0, 1.0, "Sin meses intermedios: factor 1,0.")

    factor = 1.0
    seen = 0
    for key in months:
        rate = inflation_yoy.get(key)
        if rate is None:
            continue
        seen += 1
        factor *= (1.0 + rate / 100.0) ** (1.0 / 12.0)

    coverage = seen / len(months)
    if seen == 0:
        return DeflatorResult(
            None, 0.0,
            "Sin observaciones de inflación en el tramo: el dato se mantiene NOMINAL.",
        )
    if coverage < 1.0:
        # Scale the observed months up to the full span rather than silently
        # under-deflating: an incomplete chain would understate the correction.
        factor = factor ** (1.0 / coverage)
    note = (
        f"Nivel de precios encadenado sobre {seen}/{len(months)} meses "
        f"(cobertura {coverage * 100:.0f}%)."
        + ("" if coverage == 1.0 else " Tramo incompleto extrapolado a la ventana completa.")
    )
    return DeflatorResult(factor, coverage, note)


def to_real(nominal: float, factor: Optional[float]) -> Optional[float]:
    """Express a nominal amount in base-period pesos."""
    if factor is None or factor <= 0:
        return None
    return nominal / factor


# ── bracket arithmetic ────────────────────────────────────────────────

@dataclass(frozen=True)
class Bracket:
    """A declared spend range and the share of respondents in it."""

    label: str
    midpoint: float
    share_pct: float
    is_open_ended: bool = False


def weighted_average(brackets: Sequence[Bracket]) -> Optional[float]:
    """Average spend implied by the bracket distribution."""
    total_share = sum(b.share_pct for b in brackets)
    if total_share <= 0:
        return None
    return sum(b.midpoint * b.share_pct for b in brackets) / total_share


def open_bracket_sensitivity(
    brackets: Sequence[Bracket], candidates: Sequence[float]
) -> List[Tuple[float, Optional[float]]]:
    """Recompute the average across plausible midpoints for the open-ended bracket.

    Returns ``[(assumed_midpoint, average), ...]``. A finding that flips sign across this
    range is an artefact of the assumption, not a result, and must not be reported.
    """
    out: List[Tuple[float, Optional[float]]] = []
    for cand in candidates:
        adjusted = [
            Bracket(b.label, cand if b.is_open_ended else b.midpoint,
                    b.share_pct, b.is_open_ended)
            for b in brackets
        ]
        out.append((cand, weighted_average(adjusted)))
    return out


def real_series(
    nominal_by_wave: Dict[str, float],
    wave_dates: Dict[str, date],
    inflation_yoy: Dict[str, float],
    base_wave: str,
) -> Dict[str, Optional[float]]:
    """Deflate a nominal series to the base wave's pesos."""
    base_date = wave_dates.get(base_wave)
    if base_date is None:
        return {w: None for w in nominal_by_wave}
    out: Dict[str, Optional[float]] = {}
    for wave, nominal in nominal_by_wave.items():
        d = wave_dates.get(wave)
        if d is None:
            out[wave] = None
            continue
        res = price_level_factor(inflation_yoy, base_date, d)
        out[wave] = to_real(nominal, res.factor)
    return out
