"""Category engine — the denominator the tracker does not build.

A brand tracker measures the numerator: what the consumer thinks and declares about each
brand. It rarely states how big the category itself is, so a brand can lose declared
preference while gaining ground, or gain preference inside a shrinking category, and the
report reads the same either way.

This engine builds the denominator from reach-type metrics and derives:

* **Category size** — the sum of reach across the brands flagged as in-set.
* **Share of category** — each brand's slice, wave by wave.
* **Share shift** — who gained ground and, by arithmetic, at whose expense.
* **Attitude vs behaviour** — declared preference against effective traffic share. When
  these two diverge, the divergence *is* the diagnosis, and neither series alone shows it.

Everything here is a pure function over plain structures: no database, no ORM. The service
layer loads cells and calls in. That is what makes the arithmetic testable in isolation.

**Honest bound, carried into the report:** this is share of *declared reach within the
measured set*, not market share. It excludes independents, informal trade and any chain
outside the study. The reports must say so wherever the number appears.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Cell:
    """One observation, flattened for the engines."""

    wave: str                      # wave code, e.g. "2026-03"
    brand: Optional[str]           # brand slug; None = category-level
    value: float
    base_n: Optional[int] = None


@dataclass(frozen=True)
class SharePoint:
    wave: str
    brand: str
    reach: float
    share: float


def _by_wave(cells: Sequence[Cell]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for c in cells:
        if c.brand is None:
            continue
        out.setdefault(c.wave, {})[c.brand] = c.value
    return out


def category_size(
    cells: Sequence[Cell], in_set: Optional[Sequence[str]] = None
) -> Dict[str, float]:
    """Sum of reach across in-set brands, per wave.

    Not a population estimate — an index of category activity. Its value is comparative:
    whether the pie grew, shrank or stayed flat between waves.
    """
    grid = _by_wave(cells)
    allowed = set(in_set) if in_set is not None else None
    return {
        wave: sum(v for b, v in brands.items() if allowed is None or b in allowed)
        for wave, brands in grid.items()
    }


def share_by_brand(
    cells: Sequence[Cell], in_set: Optional[Sequence[str]] = None
) -> List[SharePoint]:
    """Each in-set brand's share of the category, per wave."""
    grid = _by_wave(cells)
    sizes = category_size(cells, in_set)
    allowed = set(in_set) if in_set is not None else None
    out: List[SharePoint] = []
    for wave, brands in grid.items():
        total = sizes.get(wave) or 0.0
        if total <= 0:
            continue
        for brand, reach in brands.items():
            if allowed is not None and brand not in allowed:
                continue
            out.append(SharePoint(wave, brand, reach, reach / total * 100.0))
    return out


def category_growth(sizes: Dict[str, float], waves: Sequence[str]) -> Optional[float]:
    """Percent change in category size between the first and last wave given."""
    ordered = [w for w in waves if w in sizes]
    if len(ordered) < 2:
        return None
    first, last = sizes[ordered[0]], sizes[ordered[-1]]
    if not first:
        return None
    return (last / first - 1.0) * 100.0


def share_shift(
    points: Sequence[SharePoint], waves: Sequence[str]
) -> List[Dict[str, Any]]:
    """Share change per brand between the first and last wave, ranked by gain.

    The arithmetic identity behind the reading: shares sum to 100, so the gainers' total
    equals the losers' total. That is what licenses saying a rival's growth "came from"
    particular brands — not a causal claim, an accounting one, and the report says so.
    """
    ordered = [w for w in waves if any(p.wave == w for p in points)]
    if len(ordered) < 2:
        return []
    first, last = ordered[0], ordered[-1]
    idx: Dict[str, Dict[str, float]] = {}
    for p in points:
        if p.wave in (first, last):
            idx.setdefault(p.brand, {})[p.wave] = p.share
    rows: List[Dict[str, Any]] = [
        {
            "brand": brand,
            "share_first": vals[first],
            "share_last": vals[last],
            "delta": vals[last] - vals[first],
        }
        for brand, vals in idx.items()
        if first in vals and last in vals
    ]
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows


@dataclass(frozen=True)
class DivergencePoint:
    wave: str
    attitude: Optional[float]      # declared preference
    behaviour: Optional[float]     # effective share of category traffic


def attitude_vs_behaviour(
    attitude_cells: Sequence[Cell],
    behaviour_points: Sequence[SharePoint],
    brand: str,
    waves: Sequence[str],
) -> List[DivergencePoint]:
    """Declared preference against effective traffic share, aligned wave by wave."""
    att = {c.wave: c.value for c in attitude_cells if c.brand == brand}
    beh = {p.wave: p.share for p in behaviour_points if p.brand == brand}
    return [DivergencePoint(w, att.get(w), beh.get(w)) for w in waves]


def divergence_reading(points: Sequence[DivergencePoint]) -> Optional[Dict[str, object]]:
    """Whether attitude and behaviour moved in opposite directions in the last step.

    Returns None when either series is incomplete — an absent reading rather than a
    guessed one.
    """
    # Unpacked into plain floats rather than filtered in place: the guard and the
    # arithmetic then live in the same expression, so a later edit cannot separate them.
    usable = [(p.wave, p.attitude, p.behaviour) for p in points
              if p.attitude is not None and p.behaviour is not None]
    if len(usable) < 2:
        return None
    (prev_wave, att_prev, beh_prev) = usable[-2]
    (curr_wave, att_curr, beh_curr) = usable[-1]
    d_att = att_curr - att_prev
    d_beh = beh_curr - beh_prev
    diverging = (d_att > 0) != (d_beh > 0) and d_att != 0 and d_beh != 0
    return {
        "wave_from": prev_wave,
        "wave_to": curr_wave,
        "delta_attitude": d_att,
        "delta_behaviour": d_beh,
        "diverging": diverging,
        "direction": (
            "converting_above_attitude" if diverging and d_beh > 0
            else "attitude_above_conversion" if diverging
            else "aligned"
        ),
    }


def attribution(
    brand_delta: Optional[float],
    category_delta_pct: Optional[float],
    brand_value_prev: Optional[float],
) -> Optional[Dict[str, float]]:
    """Split a brand's movement into what the category explains and what it does not.

    ``category_effect`` is the movement the brand would have shown by merely holding its
    share while the category moved; ``brand_effect`` is the residual — the part that is
    the brand's own. It is a decomposition, not a causal model, and it answers the
    question that decides whether to act: did we move, or did the market move under us?
    """
    if brand_delta is None or category_delta_pct is None or not brand_value_prev:
        return None
    category_effect = brand_value_prev * (category_delta_pct / 100.0)
    return {
        "total_delta": brand_delta,
        "category_effect": category_effect,
        "brand_effect": brand_delta - category_effect,
    }
