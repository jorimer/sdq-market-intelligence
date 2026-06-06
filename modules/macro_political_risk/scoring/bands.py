"""IRMP risk bands — derived from doctrine, delegating to the shared mapper.

Higher score = lower risk, so bands run from 'Bajo' (best) to 'Alto' (worst).
The band definitions come from ``shared/doctrine/regulatory.yaml`` via
``IRMP_CONFIG``; the ``(name, lower, upper)`` tuples and color map below are
reconstructed for backward compatibility with existing imports.
"""
from typing import Dict, List, Tuple

from shared.indices import bands as _generic
from modules.macro_political_risk.scoring.weights import IRMP_CONFIG

_BANDS = IRMP_CONFIG.bands  # descending by lower

# (band_name, lower_inclusive, upper_inclusive) — ascending, gap-free over 0-100.
_ascending = sorted(_BANDS, key=lambda b: b.lower)
RISK_BANDS: List[Tuple[str, float, float]] = [
    (
        band.name,
        band.lower,
        (round(_ascending[i + 1].lower - 0.01, 2) if i + 1 < len(_ascending) else 100.0),
    )
    for i, band in enumerate(_ascending)
]

BAND_COLORS: Dict[str, str] = {b.name: b.color for b in _BANDS}

# Descending lower-bound thresholds — gap-free, no overlap.
BAND_THRESHOLDS = [(b.name, b.lower) for b in _BANDS]


def map_risk_band(score: float) -> str:
    """Map a 0-100 IRMP score to its risk band (higher score = lower risk).

    >>> map_risk_band(95)
    'Bajo'
    >>> map_risk_band(79.99)
    'Moderado'
    >>> map_risk_band(39.99)
    'Alto'
    >>> map_risk_band(60)
    'Moderado'
    """
    return _generic.map_band(score, _BANDS)


def get_band_color(band: str) -> str:
    return _generic.get_band_color(band, _BANDS)
