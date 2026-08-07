"""Tests for the generic explainable-index engine."""
import pytest

from shared.indices import Band, IndexConfig, run_index
from shared.indices.bands import get_band_color, map_band
from shared.indices.dimensions import compute_all_dimensions, compute_dimension
from shared.indices.normalization import normalize_value, normalize_variable


def _config(**over) -> IndexConfig:
    base = dict(
        name="TEST",
        dimension_weights={"a": 0.5, "b": 0.5},
        dimension_variables={"a": ["x", "y"], "b": ["z"]},
        risk_increasing=frozenset({"y"}),
        bands=(
            Band("Alto", 66.0, "#0a0"),
            Band("Medio", 33.0, "#fa0"),
            Band("Bajo", 0.0, "#a00"),
        ),
    )
    base.update(over)
    return IndexConfig(**base)


DATASET = {
    "DO": {"x": 10.0, "y": 2.0, "z": 50.0},
    "CR": {"x": 5.0, "y": 8.0, "z": 50.0},
    "PA": {"x": 0.0, "y": 5.0, "z": 50.0},
}


# ── config validation ────────────────────────────────────────────

class TestIndexConfig:
    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="suman"):
            _config(dimension_weights={"a": 0.5, "b": 0.4},
                    dimension_variables={"a": ["x"], "b": ["z"]})

    def test_dimensions_must_match(self):
        with pytest.raises(ValueError, match="no coinciden"):
            _config(dimension_variables={"a": ["x"], "c": ["z"]})

    def test_bands_must_descend(self):
        with pytest.raises(ValueError, match="descendentes"):
            _config(bands=(Band("Bajo", 0.0, "#a00"), Band("Alto", 66.0, "#0a0")))

    def test_bottom_band_must_start_at_zero(self):
        with pytest.raises(ValueError, match="empezar en 0"):
            _config(bands=(Band("Alto", 66.0, "#0a0"), Band("Bajo", 10.0, "#a00")))

    def test_variable_order_is_dimension_ordered(self):
        assert _config().variable_order == ["x", "y", "z"]


# ── normalization ────────────────────────────────────────────────

class TestNormalization:
    def test_basic(self):
        assert normalize_value(5, 0, 10) == 50.0
        assert normalize_value(10, 0, 10, invert=True) == 0.0

    def test_no_spread_neutral(self):
        assert normalize_value(7, 7, 7) == 50.0

    def test_clamped(self):
        assert normalize_value(20, 0, 10) == 100.0
        assert normalize_value(-5, 0, 10) == 0.0

    def test_variable_ignores_none_and_empty(self):
        assert normalize_variable(10, [0, None, 10]) == 100.0
        assert normalize_variable(5, []) == 50.0


# ── dimensions ───────────────────────────────────────────────────

class TestDimensions:
    def test_max_value_normalizes_to_top(self):
        res = compute_dimension("a", "DO", DATASET, _config())
        assert res["variables"]["x"]["normalized"] == 100.0

    def test_risk_increasing_is_inverted(self):
        res = compute_dimension("a", "DO", DATASET, _config())
        # DO has the lowest y → inverted → best (100)
        assert res["variables"]["y"]["inverted"] is True
        assert res["variables"]["y"]["normalized"] == 100.0

    def test_missing_variable_skipped_not_interpolated(self):
        ds = {"DO": {"x": 10.0}, "CR": {"x": 5.0}}
        res = compute_dimension("a", "DO", ds, _config())
        assert set(res["variables"].keys()) == {"x"}

    def test_all_none_gives_zero(self):
        ds = {"DO": {}, "CR": {}}
        res = compute_dimension("a", "DO", ds, _config())
        assert res["score"] == 0.0

    def test_compute_all_returns_every_dimension(self):
        dims = compute_all_dimensions("DO", DATASET, _config())
        assert set(dims) == {"a", "b"}


# ── bands ─────────────────────────────────────────────────────────

class TestBands:
    def test_map_band(self):
        bands = _config().bands
        assert map_band(100, bands) == "Alto"
        assert map_band(66, bands) == "Alto"
        assert map_band(65.99, bands) == "Medio"
        assert map_band(0, bands) == "Bajo"

    def test_band_color_and_fallback(self):
        bands = _config().bands
        assert get_band_color("Alto", bands) == "#0a0"
        assert get_band_color("???", bands) == "#6B7280"


# ── engine ────────────────────────────────────────────────────────

class TestEngine:
    def test_score_in_range_and_banded(self):
        res = run_index("DO", DATASET, _config())
        assert 0.0 <= res["score"] <= 100.0
        assert res["band"] in {"Alto", "Medio", "Bajo"}
        assert res["band_color"].startswith("#")
        assert res["index"] == "TEST"

    def test_unknown_entity_raises(self):
        with pytest.raises(KeyError):
            run_index("XX", DATASET, _config())

    def test_contributions_sum_to_overall(self):
        res = run_index("DO", DATASET, _config())
        total = sum(d["contribution"] for d in res["dimensions"].values())
        assert abs(total - res["score"]) <= 0.5

    def test_contribution_is_score_times_weight(self):
        res = run_index("DO", DATASET, _config())
        for d in res["dimensions"].values():
            assert d["contribution"] == round(d["score"] * d["weight"], 2)


# ── robust_bounds — peer min-max que no se deja dominar por un outlier ──────────

def test_robust_bounds_sin_outliers_no_cambia_nada():
    """Panel limpio → min/max intactos. El fix no debe mover paneles sanos."""
    from shared.indices.normalization import robust_bounds
    assert robust_bounds([1, 2, 3, 4, 5]) == (1.0, 5.0)


def test_robust_bounds_acota_el_outlier():
    """Un valor extremo deja de estirar el límite; el resto recupera dispersión."""
    from shared.indices.normalization import robust_bounds
    lo, hi = robust_bounds(list(range(1, 20)) + [500])
    assert hi < 500 and lo == 1.0


def test_robust_bounds_panel_chico_no_recorta():
    """Debajo del panel mínimo, min/max crudos: el IQR subestimaría la dispersión real.

    Caso medido: con las 7 AFP del ISA la valla acotaba los DOS extremos de rentabilidad
    (5.99-8.78 → 7.21-8.33), exagerando la diferencia entre la mejor y la peor.
    """
    from shared.indices.normalization import robust_bounds
    assert robust_bounds([1, 50, 100]) == (1.0, 100.0)
    assert robust_bounds([7]) == (7.0, 7.0)
    afp_rentabilidad = [5.99, 7.21, 7.4, 7.83, 8.05, 8.33, 8.78]
    assert robust_bounds(afp_rentabilidad) == (5.99, 8.78)


def test_robust_bounds_nunca_expande_mas_alla_del_dato():
    """La valla acota hacia adentro; jamás inventa un rango mayor al observado."""
    from shared.indices.normalization import robust_bounds
    vals = [10, 11, 12, 13, 14, 15]
    lo, hi = robust_bounds(vals)
    assert lo >= min(vals) and hi <= max(vals)
