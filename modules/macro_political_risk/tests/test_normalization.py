"""Tests for IRMP normalization."""
import pytest
from modules.macro_political_risk.scoring.normalization import (
    normalize_value, normalize_variable,
)


class TestNormalizeValue:
    @pytest.mark.parametrize("value,vmin,vmax,expected", [
        (10, 0, 10, 100.0),
        (0, 0, 10, 0.0),
        (5, 0, 10, 50.0),
    ])
    def test_no_invert(self, value, vmin, vmax, expected):
        assert normalize_value(value, vmin, vmax) == expected

    @pytest.mark.parametrize("value,vmin,vmax,expected", [
        (10, 0, 10, 0.0),
        (0, 0, 10, 100.0),
        (5, 0, 10, 50.0),
    ])
    def test_invert(self, value, vmin, vmax, expected):
        assert normalize_value(value, vmin, vmax, invert=True) == expected

    def test_no_spread_returns_neutral(self):
        assert normalize_value(7, 7, 7) == 50.0
        assert normalize_value(7, 7, 7, invert=True) == 50.0

    def test_clamped_to_range(self):
        assert normalize_value(20, 0, 10) == 100.0
        assert normalize_value(-5, 0, 10) == 0.0


class TestNormalizeVariable:
    def test_against_regional_distribution(self):
        assert normalize_variable(5, [0, 10]) == 50.0

    def test_empty_regional_returns_neutral(self):
        assert normalize_variable(5, []) == 50.0

    def test_ignores_none(self):
        assert normalize_variable(10, [0, None, 10]) == 100.0
