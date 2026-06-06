"""SGPS Acceleration factor — derived from upstream axis signals.

Doctrine: the SGPS *Acceleration* (25%) reads the current environment from
``macro.updated``, ``irmp.updated`` and ``trade.updated`` (via the
:class:`AccelerationContext`).  Explainable: starts at a neutral 50 and is nudged
by macro fragility, macro-political risk and trade resilience.
"""
from typing import Dict

from modules.sector_intel.events import AccelerationContext

# Sensitivity of each component (points per unit), kept modest and explainable.
_IRMP_SENS = 0.4          # (irmp_score - 50) * sens
_TRADE_SENS = 0.4         # (resilience - 50) * sens
_MACRO_SIGNAL_PENALTY = 5.0   # points subtracted per early-warning signal


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_acceleration(context: AccelerationContext, country_code: str = "DO") -> Dict:
    """Compute the 0-100 acceleration factor from the current upstream context."""
    base = 50.0
    components: Dict[str, float] = {}

    irmp = context.irmp.get(country_code)
    if irmp and irmp.get("irmp_score") is not None:
        components["irmp"] = round((irmp["irmp_score"] - 50.0) * _IRMP_SENS, 2)

    if context.trade and context.trade.get("resilience_score") is not None:
        components["trade"] = round((context.trade["resilience_score"] - 50.0) * _TRADE_SENS, 2)

    if context.macro and context.macro.get("signal_count") is not None:
        components["macro"] = round(-_MACRO_SIGNAL_PENALTY * context.macro["signal_count"], 2)

    score = round(_clamp(base + sum(components.values())), 2)
    return {
        "acceleration": score,
        "base": base,
        "components": components,
        "inputs_present": sorted(components.keys()),
    }
