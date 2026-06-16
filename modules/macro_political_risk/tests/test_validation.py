"""Tests for the IRMP backtest pure logic (no network/BigQuery)."""
from modules.macro_political_risk.validation.outcomes import (
    _instability_spike,
    label_panel_governance,
)
from modules.macro_political_risk.validation.report import _metrics_for, _spearman
from shared.data.gdelt_bq_client import INSTABILITY_ROOTS, build_events_query


# ── instability spike (governance outcome) ──────────────────────

def test_instability_spike_detects_forward_surge():
    # baseline (2018-2020) ~ 100; 2021 jumps to 200 (>1.5×) → spike for year 2020
    ev = {2018: 90, 2019: 100, 2020: 110, 2021: 200, 2022: 120}
    assert _instability_spike(ev, 2020) == 1


def test_instability_spike_no_surge():
    ev = {2018: 90, 2019: 100, 2020: 110, 2021: 120, 2022: 115}
    assert _instability_spike(ev, 2020) == 0


def test_instability_spike_none_when_missing_lookahead_or_baseline():
    assert _instability_spike({2020: 100}, 2020) is None          # <2 baseline points
    assert _instability_spike({2019: 100, 2020: 110}, 2020) is None  # no forward years


def test_label_panel_governance_drops_unlabelable():
    panel = [
        {"iso": "DO", "year": 2020, "irmp_score": 50.0, "risk_band": "Elevado"},
        {"iso": "CR", "year": 2020, "irmp_score": 65.0, "risk_band": "Moderado"},  # no events → dropped
    ]
    events = {"DO": {2018: 50, 2019: 60, 2020: 55, 2021: 200}}
    labeled = label_panel_governance(panel, events)
    assert len(labeled) == 1 and labeled[0]["iso"] == "DO" and labeled[0]["label"] == 1


# ── metrics + spearman ──────────────────────────────────────────

def test_metrics_for_perfect_discrimination():
    # lower IRMP = events → Gini 1; band order best→worst should be monotonic
    labeled = [
        {"iso": "A", "year": 2020, "irmp_score": 30.0, "risk_band": "Alto", "label": 1},
        {"iso": "B", "year": 2020, "irmp_score": 40.0, "risk_band": "Elevado", "label": 1},
        {"iso": "C", "year": 2020, "irmp_score": 70.0, "risk_band": "Moderado", "label": 0},
        {"iso": "D", "year": 2020, "irmp_score": 85.0, "risk_band": "Bajo", "label": 0},
    ]
    m = _metrics_for(labeled)
    assert m["gini"] == 1.0 and m["n_events"] == 2 and m["monotonic"] is True


def test_spearman_perfect_and_inverse():
    assert _spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert _spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


# ── events query ────────────────────────────────────────────────

def test_events_query_filters_instability_roots_and_countries():
    q = build_events_query()
    assert "gdelt-bq.gdeltv2.events" in q
    assert "@start_year" in q and "@fips" in q
    for root in INSTABILITY_ROOTS:
        assert f"'{root}'" in q
