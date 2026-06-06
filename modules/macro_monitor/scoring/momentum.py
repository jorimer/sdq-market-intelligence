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


def compute_series_momentum(observations: List[Observation]) -> Dict:
    """Compute momentum metrics for one chronologically-ordered series.

    Returns latest value, period-over-period change & % change, acceleration,
    a qualitative trend, recent volatility, an uncertainty band around the next
    projected value, and a probabilistic continuity read.
    """
    # Drop gaps; keep order.
    clean = [(p, float(v)) for p, v in observations if v is not None]

    base = {
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
    pct_change = round(change / abs(prev) * 100, 2) if prev != 0 else None
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
        change=change,
        pct_change=pct_change,
        acceleration=acceleration,
        trend=_trend(change, acceleration),
        volatility=volatility,
        uncertainty_band=uncertainty_band,
        continuity_prob=_continuity_prob(changes),
    )
    return base
