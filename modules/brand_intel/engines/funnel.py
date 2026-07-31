"""Funnel engine — where the brand actually leaks.

A tracker reports each rung of the ladder (awareness, ever tried, last 3 months, last
month, last 7 days) as a separate number. Conversion *between* rungs is where the
diagnosis lives: a brand can lead awareness and still lose, because the loss happens one
step later.

Step conversion normalises brand size away, so a small brand and a large one are
comparable rung by rung — which is what makes "our weakest step versus the set's best" a
usable statement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.brand_intel.engines.metrics import FUNNEL_LADDER, label_for


@dataclass(frozen=True)
class FunnelStep:
    from_metric: str
    to_metric: str
    label: str
    conversion: Optional[float]     # percent


@dataclass(frozen=True)
class BrandFunnel:
    brand: str
    rungs: Dict[str, Optional[float]]
    steps: List[FunnelStep]
    end_to_end: Optional[float]


def build_funnel(brand: str, rungs: Dict[str, Optional[float]]) -> BrandFunnel:
    """Conversion at each rung of the ladder for one brand, in one wave."""
    steps: List[FunnelStep] = []
    for a, b in zip(FUNNEL_LADDER, FUNNEL_LADDER[1:]):
        va, vb = rungs.get(a), rungs.get(b)
        conv = (vb / va * 100.0) if va and vb is not None and va > 0 else None
        steps.append(FunnelStep(a, b, f"{label_for(a)} → {label_for(b)}", conv))

    first, last = rungs.get(FUNNEL_LADDER[0]), rungs.get(FUNNEL_LADDER[-1])
    e2e = (last / first * 100.0) if first and last is not None and first > 0 else None
    return BrandFunnel(brand, rungs, steps, e2e)


def weakest_step(focal: BrandFunnel, peers: Sequence[BrandFunnel]) -> Optional[Dict[str, object]]:
    """The rung where the focal brand trails the set's best by the widest margin.

    Returns the gap and who sets the benchmark. This is the single most actionable output
    of the funnel: it names *which* step to fix rather than restating that the brand is
    behind overall.
    """
    best_gap: Optional[Dict[str, Any]] = None
    best_value: Optional[float] = None
    for i, step in enumerate(focal.steps):
        if step.conversion is None:
            continue
        # Built with an explicit loop rather than a comprehension so the None check and
        # the value it admits are the same expression — a filtered comprehension reads
        # the attribute twice, and only the second read reaches the arithmetic.
        rivals: List[Tuple[str, float]] = []
        for p in peers:
            if p.brand == focal.brand or i >= len(p.steps):
                continue
            conv = p.steps[i].conversion
            if conv is not None:
                rivals.append((p.brand, conv))
        if not rivals:
            continue
        leader, leader_conv = max(rivals, key=lambda r: r[1])
        gap = leader_conv - step.conversion
        if best_value is None or gap > best_value:
            best_value = gap
            best_gap = {
                "step_label": step.label,
                "from_metric": step.from_metric,
                "to_metric": step.to_metric,
                "focal_conversion": step.conversion,
                "leader": leader,
                "leader_conversion": leader_conv,
                "gap": gap,
            }
    return best_gap


def step_gap_series(
    focal_by_wave: Dict[str, BrandFunnel],
    rival_by_wave: Dict[str, BrandFunnel],
    step_index: int,
    waves: Sequence[str],
) -> List[Dict[str, Any]]:
    """The same step, tracked across waves against one rival.

    A gap that holds wave after wave is structural; one that appears once is noise. This
    is what lets the report distinguish the two instead of asserting either.
    """
    rows: List[Dict[str, Any]] = []
    for w in waves:
        f = focal_by_wave.get(w)
        r = rival_by_wave.get(w)
        fc = f.steps[step_index].conversion if f and step_index < len(f.steps) else None
        rc = r.steps[step_index].conversion if r and step_index < len(r.steps) else None
        rows.append({
            "wave": w,
            "focal": fc,
            "rival": rc,
            "gap": (rc - fc) if fc is not None and rc is not None else None,
        })
    return rows
