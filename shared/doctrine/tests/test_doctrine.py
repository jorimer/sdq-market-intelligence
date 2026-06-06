"""Tests for the doctrine loader."""
import pytest

from shared.doctrine import available_axes, load_doctrine
from shared.indices import IndexConfig


def test_regulatory_axis_available():
    assert "regulatory" in available_axes()


def test_loads_irmp_config():
    cfg = load_doctrine("regulatory")
    assert isinstance(cfg, IndexConfig)
    assert cfg.name == "IRMP"
    assert round(sum(cfg.dimension_weights.values()), 6) == 1.0
    assert "public_debt_gdp" in cfg.risk_increasing


def test_unknown_axis_raises():
    with pytest.raises(FileNotFoundError):
        load_doctrine("does_not_exist")


def test_loader_is_cached():
    assert load_doctrine("regulatory") is load_doctrine("regulatory")
