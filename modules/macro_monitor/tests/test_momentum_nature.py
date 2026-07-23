"""El momentum se lee según la NATURALEZA de la serie, no con una regla única.

Causa raíz que estos tests fijan: el motor aplicaba variación porcentual a todo, y eso es
un error de categoría en el 37% del catálogo. Una tasa que pasa de 4.23% a 5.35% subió
1.12 PUNTOS; reportar "+26.48%" se lee como que la inflación subió 26%.
"""
from modules.macro_monitor.scoring.momentum import compute_series_momentum as momentum


def test_a_rate_reports_percentage_points_never_percent_of_percent():
    r = momentum([("2025-04", 4.23), ("2025-05", 5.35)], nature="rate")
    assert r["change"] == 1.12
    assert r["change_unit"] == "puntos porcentuales"
    assert r["pct_change"] is None
    assert "puntos porcentuales" in r["pct_change_reason"]


def test_a_flow_reports_percent():
    r = momentum([("2024", 1000.0), ("2025", 1200.0)], nature="flow")
    assert r["pct_change"] == 20.0 and r["change_unit"] == "%"
    assert r["pct_change_reason"] is None


def test_an_index_reports_percent():
    r = momentum([("2024", 100.0), ("2025", 105.0)], nature="index")
    assert r["pct_change"] == 5.0


def test_a_stock_crossing_zero_declines_to_compute_percent():
    """Una posición neta que pasa de −50 a +30 no admite variación porcentual: el
    cociente da un número, pero no es una variación interpretable."""
    r = momentum([("2024", -50.0), ("2025", 30.0)], nature="stock")
    assert r["change"] == 80.0
    assert r["pct_change"] is None and "cruza el cero" in r["pct_change_reason"]


def test_a_negligible_base_declines_instead_of_exploding():
    """El caso de los 12 millones por ciento: base despreciable frente a la escala."""
    r = momentum([("2012", 0.8), ("2013", 12983.86)], nature="stock")
    assert r["pct_change"] is None and "despreciable" in r["pct_change_reason"]


def test_a_stock_with_a_stable_sign_does_report_percent():
    """La guarda no es un veto general a los stocks: donde el porcentaje significa algo,
    se emite."""
    r = momentum([("2024", 10000.0), ("2025", 11000.0)], nature="stock")
    assert r["pct_change"] == 10.0


def test_an_undeclared_nature_never_guesses():
    """Sin naturaleza declarada NO se elige una transformación: se declara la razón."""
    r = momentum([("2024", 100.0), ("2025", 120.0)])
    assert r["pct_change"] is None and "no declarada" in r["pct_change_reason"]
    assert r["change"] == 20.0        # el cambio de nivel siempre es válido


def test_zero_previous_period_is_undefined_not_zero():
    r = momentum([("2024", 0.0), ("2025", 5.0)], nature="flow")
    assert r["pct_change"] is None and "cero" in r["pct_change_reason"]
