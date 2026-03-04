"""SDQ Rating Scale — 10-tier credit rating system.

Maps continuous scores [0-100] to rating tiers SDQ-AAA through SDQ-D.
Extracted from financial-analysis-agent/banking_scoring_service.py.
"""
from typing import Dict, List, Optional, Tuple

# (tier_name, lower_bound_inclusive, upper_bound_inclusive)
RATING_SCALE: List[Tuple[str, float, float]] = [
    ("SDQ-AAA",  95.0, 100.0),
    ("SDQ-AA+",  90.0,  94.99),
    ("SDQ-AA",   85.0,  89.99),
    ("SDQ-AA-",  80.0,  84.99),
    ("SDQ-A+",   75.0,  79.99),
    ("SDQ-A",    70.0,  74.99),
    ("SDQ-A-",   65.0,  69.99),
    ("SDQ-BBB+", 55.0,  64.99),
    ("SDQ-BBB",  45.0,  54.99),
    ("SDQ-D",     0.0,  44.99),
]

TIER_COLORS: Dict[str, str] = {
    "SDQ-AAA":  "#047857",
    "SDQ-AA+":  "#059669",
    "SDQ-AA":   "#10B981",
    "SDQ-AA-":  "#34D399",
    "SDQ-A+":   "#3B82F6",
    "SDQ-A":    "#60A5FA",
    "SDQ-A-":   "#F59E0B",
    "SDQ-BBB+": "#F97316",
    "SDQ-BBB":  "#EF4444",
    "SDQ-D":    "#991B1B",
}

# Lookup dicts: tier name ↔ ordinal index (0 = best)
RATING_TIER_TO_INDEX: Dict[str, int] = {
    tier: i for i, (tier, _, _) in enumerate(RATING_SCALE)
}
INDEX_TO_RATING_TIER: Dict[int, str] = {
    i: tier for tier, i in RATING_TIER_TO_INDEX.items()
}

# Lower-bound thresholds that separate adjacent tiers (descending)
TIER_BOUNDARIES: List[float] = [95.0, 90.0, 85.0, 80.0, 75.0, 70.0, 65.0, 55.0, 45.0]

# Action-type labels in Spanish
ACTION_TYPE_LABELS: Dict[str, str] = {
    "upgrade": "Elevación",
    "downgrade": "Reducción",
    "confirmacion": "Confirmación",
    "observacion": "Observación",
}


def map_rating_tier(score: float) -> str:
    """Map a continuous score [0-100] to its SDQ rating tier.

    >>> map_rating_tier(97.5)
    'SDQ-AAA'
    >>> map_rating_tier(44.99)
    'SDQ-D'
    >>> map_rating_tier(45.0)
    'SDQ-BBB'
    """
    for tier, lo, hi in RATING_SCALE:
        if lo <= score <= hi:
            return tier
    return "SDQ-D"


def get_tier_color(tier: str) -> str:
    """Return the hex color for a given rating tier."""
    return TIER_COLORS.get(tier, "#6B7280")


def get_all_tiers() -> List[Dict]:
    """Return all tiers with their ranges and colors.

    >>> tiers = get_all_tiers()
    >>> len(tiers)
    10
    >>> tiers[0]['tier']
    'SDQ-AAA'
    """
    return [
        {
            "tier": tier,
            "lower": lo,
            "upper": hi,
            "color": TIER_COLORS.get(tier, "#6B7280"),
            "index": i,
        }
        for i, (tier, lo, hi) in enumerate(RATING_SCALE)
    ]


def check_boundary_proximity(
    score: float, threshold: float = 2.0
) -> Optional[Tuple[float, str]]:
    """Check if score is within *threshold* points of any tier boundary.

    Returns ``(distance, direction)`` or ``None``.
    *direction* is ``'downgrade'`` when the score sits just above a boundary
    and ``'upgrade'`` when just below.
    """
    for boundary in TIER_BOUNDARIES:
        distance = score - boundary
        if abs(distance) <= threshold:
            direction = "downgrade" if distance >= 0 else "upgrade"
            return (abs(distance), direction)
    return None
