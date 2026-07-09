"""Tests del helper de posición-en-panel (E2E-SYS1)."""
from shared.indices.panel import annotate_panel_position


def test_top_of_panel():
    pos = annotate_panel_position(90.0, [90.0, 80.0, 70.0, 60.0, 50.0])
    assert pos["rank"] == 1
    assert pos["n"] == 5
    assert pos["percentile"] == 100.0
    assert pos["distribution"]["max"] == 90.0
    assert pos["distribution"]["min"] == 50.0


def test_bottom_of_panel():
    pos = annotate_panel_position(50.0, [90.0, 80.0, 70.0, 60.0, 50.0])
    assert pos["rank"] == 5
    assert pos["percentile"] == 0.0


def test_middle_matches_irmp_case():
    # DO rank 4 de 5 (caso real IRMP): percentil 25.
    pos = annotate_panel_position(48.66, [60.37, 55.0, 52.0, 48.66, 36.45])
    assert pos["rank"] == 4
    assert pos["n"] == 5
    assert pos["percentile"] == 25.0


def test_lower_is_better_inverts():
    # Con menor = mejor, el valor más bajo es rank 1.
    pos = annotate_panel_position(10.0, [10.0, 20.0, 30.0], higher_is_better=False)
    assert pos["rank"] == 1


def test_ties_share_best_rank():
    pos = annotate_panel_position(80.0, [80.0, 80.0, 60.0])
    assert pos["rank"] == 1  # empatado arriba: nadie estrictamente mejor


def test_none_subject_returns_none():
    assert annotate_panel_position(None, [1.0, 2.0]) is None


def test_singleton_panel_returns_none():
    # Panel de 1 (o el sujeto solo): el rango no informa nada.
    assert annotate_panel_position(50.0, [50.0]) is None
