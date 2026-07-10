"""SGPS (Sector Growth Potential Score).

Doctrine §3/§5: structural potential > current size.  SGPS blends three factors:

    Histórico 40% · Estructural 35% · Aceleración 25%

The Acceleration factor comes from upstream events (see ``acceleration.py``);
historical and structural are sector inputs (0-100).
"""
from typing import Dict, Optional

# SGPS factor weights (sum to 1.0).
W_HISTORICAL = 0.40
W_STRUCTURAL = 0.35
W_ACCELERATION = 0.25


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_sgps(
    historical: Optional[float],
    structural: Optional[float],
    acceleration: float,
    sources: Optional[Dict[str, str]] = None,
) -> Dict:
    """Blend the three SGPS factors into a 0-100 score with an auditable breakdown.

    Missing historical/structural inputs are treated as neutral (50) and flagged,
    rather than silently dropped, so the score is always reconstructable.

    ``sources`` maps ``"historical"``/``"structural"`` to ``"live"`` or ``"rubric"``
    for the real-vs-rubric badge — matching the IAI provenance. Today both are
    declared rubric (doctrine defaults); when a real source lands (BCRD histórico /
    ENAE estructural) the assembler passes ``"live"``. Acceleration is always real
    (derived from upstream events). Absent/unknown → conservatively "rubric" for the
    two sector inputs (an unsourced value is declared, never assumed real).
    """
    sources = sources or {}
    hist = 50.0 if historical is None else _clamp(float(historical))
    struct = 50.0 if structural is None else _clamp(float(structural))
    accel = _clamp(float(acceleration))

    contributions = {
        "historical": round(hist * W_HISTORICAL, 2),
        "structural": round(struct * W_STRUCTURAL, 2),
        "acceleration": round(accel * W_ACCELERATION, 2),
    }
    score = round(_clamp(sum(contributions.values())), 2)

    return {
        "sgps_score": score,
        "factors": {
            "historical": {"value": hist, "weight": W_HISTORICAL,
                           "contribution": contributions["historical"],
                           "imputed": historical is None,
                           "source": sources.get("historical", "rubric")},
            "structural": {"value": struct, "weight": W_STRUCTURAL,
                           "contribution": contributions["structural"],
                           "imputed": structural is None,
                           "source": sources.get("structural", "rubric")},
            "acceleration": {"value": accel, "weight": W_ACCELERATION,
                             "contribution": contributions["acceleration"],
                             "imputed": False, "source": "live"},
        },
    }
