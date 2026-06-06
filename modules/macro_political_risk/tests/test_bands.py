"""Tests for IRMP risk bands."""
import pytest
from modules.macro_political_risk.scoring.bands import (
    RISK_BANDS, map_risk_band, get_band_color,
)


@pytest.mark.parametrize("score,band", [
    (100, "Bajo"), (80, "Bajo"),
    (79.99, "Moderado"), (60, "Moderado"),
    (59.99, "Elevado"), (40, "Elevado"),
    (39.99, "Alto"), (0, "Alto"),
])
def test_map_risk_band(score, band):
    assert map_risk_band(score) == band


def test_bands_cover_0_100_without_gaps():
    # Sorted ascending by lower bound, each lower bound continues the previous
    bounds = sorted((lo, hi) for _, lo, hi in RISK_BANDS)
    assert bounds[0][0] == 0.0
    assert bounds[-1][1] == 100.0


def test_every_band_has_color():
    for name, _, _ in RISK_BANDS:
        assert get_band_color(name).startswith("#")
