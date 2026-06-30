"""Tests del motor de gráficos de marca (PNG para PDF/Word)."""
import os

from shared.products.charts import bar_chart_png, line_chart_png, render_charts


def test_line_chart_png_creates_file(tmp_path):
    path = line_chart_png("Tendencia del IZF",
                          [("2022", 45.0), ("2023", 47.5), ("2024", 48.8), ("2025", 49.2)],
                          str(tmp_path / "t.png"))
    assert path and os.path.exists(path) and os.path.getsize(path) > 0


def test_line_chart_needs_two_points(tmp_path):
    # una línea de 1 punto no es tendencia → None (defensivo)
    assert line_chart_png("X", [("2025", 49.2)], str(tmp_path / "x.png")) is None
    assert line_chart_png("X", [("2024", None), ("2025", 1.0)], str(tmp_path / "y.png")) is None


def test_render_charts_dispatches_line(tmp_path):
    out = render_charts([{"kind": "line", "title": "Trend", "items": [("a", 1.0), ("b", 2.0)]}],
                        str(tmp_path), "pref")
    assert len(out) == 1 and out[0][0] == "Trend" and os.path.exists(out[0][1])


def test_bar_chart_png_creates_file(tmp_path):
    path = bar_chart_png("Contribución (pp)",
                         [("Financiero", 0.34), ("Construcción", -0.24)],
                         str(tmp_path / "c.png"), signed=True)
    assert path and os.path.exists(path) and path.endswith(".png")
    assert os.path.getsize(path) > 0


def test_bar_chart_empty_returns_none(tmp_path):
    # sin valores numéricos → None (defensivo, no rompe el reporte)
    assert bar_chart_png("X", [("a", None)], str(tmp_path / "x.png")) is None


def test_render_charts_skips_failed_and_empty(tmp_path):
    charts = [
        {"title": "Dim", "items": [("a", 10.0), ("b", 20.0)]},
        {"title": "Vacío", "items": []},            # se omite
        {"title": "SinValores", "items": [("z", None)]},  # se omite (None)
    ]
    out = render_charts(charts, str(tmp_path), "pref")
    assert len(out) == 1 and out[0][0] == "Dim"
    assert os.path.exists(out[0][1])
