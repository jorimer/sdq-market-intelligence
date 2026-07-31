"""Pure-engine tests: significance, category, funnel, forecast, deflation, ledger.

No database. Every expected value is arithmetic that can be redone by hand, which is the
point: these engines decide what the report is allowed to assert, so their behaviour is
pinned to computable facts rather than to whatever they happened to return first.
"""
from datetime import date

import pytest

from modules.brand_intel.engines import category as cat
from modules.brand_intel.engines import deflate as defl
from modules.brand_intel.engines import forecast as fc
from modules.brand_intel.engines import funnel as fn
from modules.brand_intel.engines import ledger as ldg
from modules.brand_intel.engines import significance as sig


# ── significance ──────────────────────────────────────────────────────

def test_confidence_halfwidth_matches_binomial_formula():
    # p=.5, n=300 → 1.96 * sqrt(.25/300) = 5.66 pp, the classic tracker margin
    assert sig.confidence_halfwidth(50.0, 300) == pytest.approx(5.66, abs=0.01)


def test_confidence_halfwidth_without_base_is_none():
    assert sig.confidence_halfwidth(50.0, None) is None
    assert sig.confidence_halfwidth(50.0, 0) is None


def test_small_base_widens_the_band():
    assert sig.confidence_halfwidth(29.0, 63) == pytest.approx(11.2, abs=0.1)


def test_detectable_threshold_between_two_proportions():
    assert sig.detectable_threshold(94, 86, 84, 88) == pytest.approx(9.2, abs=0.1)


def test_change_below_threshold_is_not_a_finding():
    a = sig.assess_change("favourite_place", 19.0, 68, 27.0, 63)
    assert a.verdict == sig.NOT_DETECTABLE
    assert not a.is_finding


def test_change_on_the_edge_is_marginal_not_significant():
    """A movement that barely clears its threshold must not be promoted to a finding."""
    a = sig.assess_change("delivery_t2b", 84.0, 88, 94.0, 86)
    assert a.verdict == sig.MARGINAL
    assert not a.is_finding
    assert "filo" in a.note


def test_clear_movement_is_significant():
    a = sig.assess_change("reach_7d", 20.0, 300, 40.0, 300)
    assert a.verdict == sig.SIGNIFICANT_UP
    assert a.is_finding


def test_missing_base_is_unscoreable_never_assumed():
    a = sig.assess_change("reach_7d", 20.0, None, 30.0, 300)
    assert a.verdict == sig.UNSCOREABLE
    assert not a.publishable


def test_base_under_thirty_is_not_publishable():
    a = sig.assess_change("reach_7d", 20.0, 25, 40.0, 300)
    assert a.verdict == sig.BASE_INSUFFICIENT
    assert not a.publishable


def test_index_metric_gets_no_confidence_band():
    """Double-indexation scores are ratios, not proportions: inventing a band would
    manufacture confidence out of nothing."""
    a = sig.assess_change("attribute_index", 153.0, 300, 176.0, 300)
    assert a.verdict == sig.UNSCOREABLE
    assert a.threshold is None
    assert a.delta == pytest.approx(23.0)


# ── category ──────────────────────────────────────────────────────────

def _reach_cells():
    return [
        cat.Cell("w1", "a", 40), cat.Cell("w1", "b", 60), cat.Cell("w1", "x", 10),
        cat.Cell("w2", "a", 45), cat.Cell("w2", "b", 55), cat.Cell("w2", "x", 10),
    ]


def test_category_size_excludes_out_of_set_brands():
    sizes = cat.category_size(_reach_cells(), in_set=["a", "b"])
    assert sizes == {"w1": 100.0, "w2": 100.0}


def test_share_is_computed_against_the_in_set_denominator():
    points = {(p.wave, p.brand): p.share
              for p in cat.share_by_brand(_reach_cells(), in_set=["a", "b"])}
    assert points[("w1", "a")] == pytest.approx(40.0)
    assert points[("w2", "a")] == pytest.approx(45.0)


def test_share_shift_ranks_gainers_first_and_sums_to_zero():
    points = cat.share_by_brand(_reach_cells(), in_set=["a", "b"])
    rows = cat.share_shift(points, ["w1", "w2"])
    assert rows[0]["brand"] == "a"
    assert sum(r["delta"] for r in rows) == pytest.approx(0.0)


def test_category_growth_between_first_and_last_wave():
    assert cat.category_growth({"w1": 100.0, "w2": 110.0}, ["w1", "w2"]) == pytest.approx(10.0)


def test_divergence_detects_opposite_directions():
    pts = [
        cat.DivergencePoint("w1", attitude=20.0, behaviour=18.0),
        cat.DivergencePoint("w2", attitude=17.0, behaviour=20.0),
    ]
    reading = cat.divergence_reading(pts)
    assert reading["diverging"] is True
    assert reading["direction"] == "converting_above_attitude"


def test_divergence_when_aligned_is_not_flagged():
    pts = [
        cat.DivergencePoint("w1", attitude=20.0, behaviour=18.0),
        cat.DivergencePoint("w2", attitude=22.0, behaviour=20.0),
    ]
    assert cat.divergence_reading(pts)["diverging"] is False


def test_divergence_requires_both_series():
    pts = [cat.DivergencePoint("w1", attitude=20.0, behaviour=None)]
    assert cat.divergence_reading(pts) is None


def test_attribution_splits_category_effect_from_brand_effect():
    # Brand went 20 → 24 (+4) while the category grew 10%: 2.0 pp of that is the category.
    out = cat.attribution(brand_delta=4.0, category_delta_pct=10.0, brand_value_prev=20.0)
    assert out["category_effect"] == pytest.approx(2.0)
    assert out["brand_effect"] == pytest.approx(2.0)


# ── funnel ────────────────────────────────────────────────────────────

def _rungs(a, b, c, d, e):
    return {"awareness_total": a, "ever_tried": b, "reach_3m": c,
            "reach_1m": d, "reach_7d": e}


def test_funnel_step_conversion_and_end_to_end():
    f = fn.build_funnel("focal", _rungs(87, 82, 60, 43, 27))
    assert f.steps[1].conversion == pytest.approx(73.2, abs=0.1)   # 60/82
    assert f.end_to_end == pytest.approx(31.0, abs=0.1)            # 27/87


def test_weakest_step_names_the_rung_and_the_benchmark():
    focal = fn.build_funnel("focal", _rungs(87, 82, 60, 43, 27))
    rival = fn.build_funnel("rival", _rungs(83, 80, 70, 53, 31))
    out = fn.weakest_step(focal, [focal, rival])
    assert out["from_metric"] == "ever_tried"
    assert out["leader"] == "rival"
    assert out["gap"] == pytest.approx(14.3, abs=0.2)


def test_funnel_handles_missing_rungs_without_inventing():
    f = fn.build_funnel("focal", {"awareness_total": 80})
    assert f.end_to_end is None
    assert all(s.conversion is None for s in f.steps)


# ── forecast ──────────────────────────────────────────────────────────

def test_backtest_ranks_rules_and_never_looks_ahead():
    ranked = fc.backtest_rules([10, 12, 11, 13])
    assert {r.rule for r in ranked} == {"persistence", "mean", "trend"}
    assert all(r.n_predictions == 2 for r in ranked)   # 4 points − 2 minimum history


def test_trend_loses_on_a_stationary_noisy_series():
    """The empirical result the report leans on: extrapolating slope is the worst rule
    on tracker series."""
    ranked = fc.backtest_rules([20, 24, 21, 25, 22, 26])
    assert ranked[-1].rule == "trend"


def test_issue_forecast_returns_band_from_the_base():
    f = fc.issue_forecast([87, 87, 87, 94], base_n=100, rule="mean")
    assert f.point == pytest.approx(88.75, abs=0.01)
    assert f.lo < f.point < f.hi
    assert f.rule == "mean"


def test_issue_forecast_declines_without_a_base():
    assert fc.issue_forecast([10, 12, 14], base_n=None) is None


def test_issue_forecast_declines_without_enough_history():
    assert fc.issue_forecast([10], base_n=300) is None


def test_score_forecast_marks_inside_and_outside_band():
    inside = fc.score_forecast(50.0, 45.0, 55.0, 52.0)
    outside = fc.score_forecast(50.0, 45.0, 55.0, 60.0)
    assert inside.inside_band and "sin novedad" in inside.note
    assert not outside.inside_band and "agenda" in outside.note
    assert outside.abs_error == pytest.approx(10.0)


# ── deflation ─────────────────────────────────────────────────────────

def test_price_level_factor_over_a_full_year_matches_the_rate():
    infl = {f"2025-{m:02d}": 12.0 for m in range(1, 13)}
    infl.update({f"2026-{m:02d}": 12.0 for m in range(1, 13)})
    res = defl.price_level_factor(infl, date(2025, 1, 1), date(2026, 1, 1))
    assert res.factor == pytest.approx(1.12, abs=0.001)


def test_deflator_absent_series_returns_none_not_one():
    """Without inflation data the caller must keep the nominal figure and say so —
    a factor of 1.0 would silently claim zero inflation."""
    res = defl.price_level_factor({}, date(2025, 1, 1), date(2026, 1, 1))
    assert res.factor is None
    assert not res.available
    assert "NOMINAL" in res.note


def test_to_real_divides_by_the_factor():
    assert defl.to_real(1120.0, 1.12) == pytest.approx(1000.0)
    assert defl.to_real(1120.0, None) is None


def test_bracket_weighted_average():
    brackets = [
        defl.Bracket("bajo", 400, 50.0),
        defl.Bracket("alto", 1000, 50.0),
    ]
    assert defl.weighted_average(brackets) == pytest.approx(700.0)


def test_real_series_deflates_every_wave_to_the_base():
    infl = {f"{y}-{m:02d}": 12.0 for y in (2025, 2026) for m in range(1, 13)}
    out = defl.real_series(
        {"w1": 1000.0, "w2": 1120.0},
        {"w1": date(2025, 1, 1), "w2": date(2026, 1, 1)},
        infl, base_wave="w1",
    )
    assert out["w1"] == pytest.approx(1000.0)
    assert out["w2"] == pytest.approx(1000.0, abs=1.0)   # nominal grew exactly with prices


def test_real_series_without_a_wave_date_yields_none_for_that_wave():
    out = defl.real_series(
        {"w1": 1000.0, "w2": 1100.0}, {"w1": date(2025, 1, 1)},
        {"2025-06": 5.0}, base_wave="w1",
    )
    assert out["w2"] is None


def test_real_series_without_a_base_date_yields_all_none():
    out = defl.real_series({"w1": 1000.0}, {}, {"2025-06": 5.0}, base_wave="w1")
    assert out == {"w1": None}


def test_price_level_factor_is_one_when_dates_do_not_advance():
    res = defl.price_level_factor({"2025-06": 5.0}, date(2026, 1, 1), date(2025, 1, 1))
    assert res.factor == pytest.approx(1.0)


def test_partial_coverage_is_reported_and_scaled_to_the_window():
    """A chain over half the months must not under-deflate silently."""
    infl = {"2025-02": 12.0, "2025-03": 12.0}      # only 2 of 12 months present
    res = defl.price_level_factor(infl, date(2025, 1, 1), date(2026, 1, 1))
    assert res.coverage == pytest.approx(2 / 12)
    assert res.factor == pytest.approx(1.12, abs=0.01)
    assert "incompleto" in res.note


def test_step_gap_series_tracks_one_rung_across_waves():
    focal = {w: fn.build_funnel("focal", _rungs(87, 82, 60, 43, 27)) for w in ("w1", "w2")}
    rival = {w: fn.build_funnel("rival", _rungs(83, 80, 70, 53, 31)) for w in ("w1", "w2")}
    rows = fn.step_gap_series(focal, rival, step_index=1, waves=["w1", "w2", "w3"])
    assert len(rows) == 3
    assert rows[0]["gap"] == pytest.approx(14.3, abs=0.2)
    assert rows[2]["gap"] is None          # wave with no data stays absent, not zero


def test_weakest_step_returns_none_without_peers():
    focal = fn.build_funnel("focal", _rungs(87, 82, 60, 43, 27))
    assert fn.weakest_step(focal, [focal]) is None


def test_open_bracket_sensitivity_moves_only_the_open_bracket():
    brackets = [
        defl.Bracket("bajo", 400, 80.0),
        defl.Bracket("abierto", 2000, 20.0, is_open_ended=True),
    ]
    out = dict(defl.open_bracket_sensitivity(brackets, [2000, 3000]))
    assert out[2000] == pytest.approx(720.0)
    assert out[3000] == pytest.approx(920.0)


# ── ledger ────────────────────────────────────────────────────────────

def test_decision_below_detection_floor_is_rejected_before_commitment():
    check = ldg.check_feasibility("favourite_place", 29.0, 63, success_threshold=5.0)
    assert not check.feasible
    assert "inevaluable" in check.reason


def test_decision_above_detection_floor_is_accepted():
    check = ldg.check_feasibility("reach_7d", 27.0, 300, success_threshold=10.0)
    assert check.feasible


def test_decision_without_threshold_is_rejected():
    check = ldg.check_feasibility("reach_7d", 27.0, 300, success_threshold=None)
    assert not check.feasible
    assert "umbral" in check.reason


def test_decision_with_tiny_base_is_rejected():
    check = ldg.check_feasibility("reach_7d", 27.0, 20, success_threshold=30.0)
    assert not check.feasible


def test_verdict_achieved_on_a_clear_improvement():
    v = ldg.evaluate("reach_7d", 20.0, 300, 40.0, 300)
    assert v.status == ldg.ACHIEVED


def test_verdict_worsened_respects_metric_direction():
    v = ldg.evaluate("reach_7d", 40.0, 300, 20.0, 300)
    assert v.status == ldg.WORSENED


def test_verdict_inconclusive_when_movement_is_under_the_threshold():
    v = ldg.evaluate("last_visit_share", 39.0, 300, 44.0, 217)
    assert v.status == ldg.INCONCLUSIVE


def test_verdict_open_until_the_target_wave_lands():
    v = ldg.evaluate("reach_7d", 20.0, 300, None, None)
    assert v.status == ldg.OPEN


def test_summary_counts_every_status():
    out = ldg.summarize([
        ldg.Verdict(ldg.ACHIEVED, 1, 1, ""),
        ldg.Verdict(ldg.INCONCLUSIVE, 1, 1, ""),
        ldg.Verdict(ldg.OPEN, None, None, ""),
    ])
    assert out == {"total": 3, "achieved": 1, "worsened": 0, "inconclusive": 1,
                   "unevaluable": 0, "open": 1, "closed": 2}
