"""Map a 0-100 score to a qualitative band, parametrized by ``IndexConfig.bands``.

Bands are ordered descending by lower bound and cover [0, 100] without gaps
(enforced in :class:`~shared.indices.config.IndexConfig`), so a single
lower-bound scan is unambiguous.
"""
from typing import Tuple

from shared.brand import MUTED
from shared.indices.config import Band

_FALLBACK_COLOR = MUTED   # gris de reserva para una banda sin color declarado


def map_band(score: float, bands: Tuple[Band, ...]) -> str:
    """Return the band name for *score* (bands descending by ``lower``)."""
    for band in bands:
        if score >= band.lower:
            return band.name
    return bands[-1].name


def get_band_color(band_name: str, bands: Tuple[Band, ...]) -> str:
    """Return the hex color for *band_name*, or a neutral gray if unknown."""
    for band in bands:
        if band.name == band_name:
            return band.color
    return _FALLBACK_COLOR
