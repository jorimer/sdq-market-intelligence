"""Tests for the S3/S4/S5 engines: attribution, scenarios and vigilance.

The recurring property under test is restraint. These three engines sit closest to the
temptation to over-claim — a macro reading that quietly adjusts a forecast, a scenario with
an invented probability, an agenda item built on a movement that never cleared its
threshold. Each of those is asserted against explicitly.
"""
import pytest

from modules.brand_intel.engines import attribution as attr
from modules.brand_intel.engines import scenarios as scn
from modules.brand_intel.engines import vigilance as vig


def _factor(direction, magnitude, label="F"):
    return {"key": label.lower(), "label": label, "direction": direction,
            "magnitude": magnitude, "reading": "lectura", "rationale": ""}


# ── environment ───────────────────────────────────────────────────────

def test_environment_unknown_when_no_usable_factors():
    """Absent macro data must not pass for a benign environment."""
    env = attr.read_environment([])
    assert env.stance == attr.UNKNOWN
    assert not env.known
    assert env.index is None


def test_environment_ignores_factors_without_a_reading():
    env = attr.read_environment([{"key": "x", "direction": "n/d", "magnitude": "n/d"}])
    assert env.stance == attr.UNKNOWN


def test_environment_demanding_when_adverse_factors_dominate():
    env = attr.read_environment([_factor("adverso", "alto"), _factor("adverso", "moderado")])
    assert env.stance == attr.DEMANDING
    assert env.index < 0
    assert env.adverse == 2


def test_environment_favourable_when_positive_factors_dominate():
    env = attr.read_environment([_factor("favorable", "alto"), _factor("favorable", "alto")])
    assert env.stance == attr.FAVOURABLE
    assert env.index == pytest.approx(1.0)


def test_environment_weights_by_declared_magnitude():
    """One high-magnitude adverse factor outweighs one low-magnitude favourable one."""
    env = attr.read_environment([_factor("adverso", "alto"), _factor("favorable", "bajo")])
    assert env.stance == attr.DEMANDING


def test_environment_neutral_when_balanced():
    env = attr.read_environment([_factor("adverso", "alto"), _factor("favorable", "alto")])
    assert env.stance == attr.NEUTRAL


# ── attribution ───────────────────────────────────────────────────────

def test_share_like_metric_is_split_between_category_and_brand():
    out = attr.decompose_indicator(
        "reach_7d", "Alcance", "w1", "w2", 20.0, 24.0,
        category_delta_pct=10.0, is_share_like=True)
    assert out.category_effect == pytest.approx(2.0)
    assert out.brand_effect == pytest.approx(2.0)
    assert out.verdict == "mixto"


def test_attitudinal_metric_is_never_attributed_to_the_category():
    """Preference does not scale with category size: splitting it would be a category
    error dressed as arithmetic."""
    out = attr.decompose_indicator(
        "favourite_place", "Preferencia", "w1", "w2", 20.0, 17.0,
        category_delta_pct=10.0, is_share_like=False)
    assert out.category_effect is None
    assert out.brand_effect == pytest.approx(-3.0)
    assert out.verdict == "solo_marca"


def test_movement_dominated_by_category_is_flagged_as_such():
    out = attr.decompose_indicator(
        "reach_7d", "Alcance", "w1", "w2", 20.0, 24.0,
        category_delta_pct=19.0, is_share_like=True)
    assert out.verdict == "categoria"
    assert "no está roto" in out.note


def test_missing_observation_yields_no_attribution():
    out = attr.decompose_indicator(
        "reach_7d", "Alcance", "w1", "w2", None, 24.0, 10.0, True)
    assert out.verdict == "sin_dato"
    assert out.delta is None


def test_cycle_reading_never_changes_the_number():
    """The environment reframes the result; it must not scale it."""
    env = attr.read_environment([_factor("adverso", "alto")])
    reading = attr.cycle_reading(2.0, env)
    assert reading["reading"] == "avanzo"
    assert "2.0" not in reading["text"] and "2,0" not in reading["text"]


def test_cycle_reading_without_context_says_so():
    reading = attr.cycle_reading(2.0, attr.read_environment([]))
    assert reading["reading"] == "sin_contexto"


def test_flat_movement_in_a_demanding_environment_reads_as_holding_ground():
    env = attr.read_environment([_factor("adverso", "alto")])
    assert attr.cycle_reading(0.1, env)["reading"] == "sostuvo"


def test_direction_respects_higher_is_better():
    env = attr.read_environment([_factor("favorable", "alto")])
    assert attr.cycle_reading(-2.0, env, higher_is_better=False)["reading"] == "avanzo"


# ── scenarios ─────────────────────────────────────────────────────────

def test_scenarios_without_macro_context_collapse_to_one():
    out = scn.build_scenarios(attr.read_environment([]))
    assert len(out) == 1
    assert out[0].band_reading == scn.SYMMETRIC


def test_three_scenarios_when_context_is_known():
    out = scn.build_scenarios(attr.read_environment([_factor("adverso", "alto")]))
    assert [s.key for s in out] == [scn.CONTINUITY, scn.DETERIORATION, scn.RELIEF]


def test_continuity_band_tilts_with_the_stance():
    demanding = scn.build_scenarios(attr.read_environment([_factor("adverso", "alto")]))
    favourable = scn.build_scenarios(attr.read_environment([_factor("favorable", "alto")]))
    assert demanding[0].band_reading == scn.DOWNSIDE
    assert favourable[0].band_reading == scn.UPSIDE


def test_no_scenario_carries_a_probability():
    """Assigning probabilities would imply a distribution nobody estimated."""
    for s in scn.build_scenarios(attr.read_environment([_factor("adverso", "alto")])):
        assert not any(ch.isdigit() and "%" in s.probability_note for ch in s.probability_note)


def test_rule_dispersion_is_robust_when_rules_agree_inside_the_band():
    out = scn.rule_dispersion("m", "Métrica", [50.0, 50.0, 50.0], band_halfwidth=5.0)
    assert out.spread == pytest.approx(0.0)
    assert out.robust is True


def test_rule_dispersion_flags_fragility_when_rules_disagree():
    out = scn.rule_dispersion("m", "Métrica", [10.0, 40.0], band_halfwidth=2.0)
    assert out.robust is False
    assert "reserva" in out.note


def test_rule_dispersion_needs_history():
    assert scn.rule_dispersion("m", "Métrica", [10.0], 5.0) is None


def test_base_sensitivity_widens_the_band_as_the_base_shrinks():
    out = scn.base_sensitivity(50.0, expected_base=300, candidates=(100, 400))
    widths = {r["base_n"]: r["halfwidth"] for r in out.rows}
    assert widths[100] > widths[400]


def test_risks_name_short_history_and_instrument_change():
    env = attr.read_environment([_factor("adverso", "alto")])
    risks = scn.forecast_risks([], n_waves=4, env=env)
    names = {r["risk"] for r in risks}
    assert "Historia corta" in names
    assert "Cambio de instrumento" in names
    assert "Entorno exigente" in names


def test_risks_flag_missing_macro_context():
    risks = scn.forecast_risks([], n_waves=10, env=attr.read_environment([]))
    assert "Sin contexto macro" in {r["risk"] for r in risks}


# ── vigilance ─────────────────────────────────────────────────────────

def _assessment(verdict, delta=5.0, label="Métrica"):
    return {"metric_code": "m", "label": label, "delta": delta, "threshold": 3.0,
            "verdict": verdict, "note": "nota", "higher_is_better": True}


def test_tracker_signals_drop_movements_below_threshold():
    """Below threshold is not a weak signal — it is the absence of one."""
    out = vig.tracker_signals([_assessment("not_detectable"), _assessment("unscoreable")])
    assert out == []


def test_tracker_signals_keep_confirmed_and_marginal():
    out = vig.tracker_signals([_assessment("significant_up"), _assessment("marginal")])
    assert {s.strength for s in out} == {"confirmada", "marginal"}


def test_tracker_signal_direction_respects_metric_polarity():
    good = vig.tracker_signals([_assessment("significant_up", delta=5.0)])[0]
    bad = vig.tracker_signals([_assessment("significant_down", delta=-5.0)])[0]
    assert good.direction == "favorable"
    assert bad.direction == "adverso"


def test_forecast_signals_only_report_misses():
    out = vig.forecast_signals([
        {"label": "A", "actual": 50.0, "point": 50.0, "inside_band": True},
        {"label": "B", "actual": 60.0, "point": 50.0, "inside_band": False},
    ])
    assert [s.label for s in out] == ["B"]
    assert out[0].strength == "confirmada"


def test_decision_signals_pick_up_worsened_and_inconclusive():
    out = vig.decision_signals([
        {"title": "A", "label": "m", "status": "worsened", "note": ""},
        {"title": "B", "label": "m", "status": "achieved", "note": ""},
        {"title": "C", "label": "m", "status": "not_detectable", "note": ""},
    ])
    assert len(out) == 2
    assert {s.strength for s in out} == {"confirmada", "marginal"}


def test_agenda_puts_a_forecast_miss_first():
    """The miss was committed to in advance — it is the strongest available evidence."""
    f = vig.forecast_signals([{"label": "Alcance", "actual": 60.0, "point": 50.0,
                               "inside_band": False}])
    t = vig.tracker_signals([_assessment("significant_up", label="Otro")])
    out = vig.build_agenda(f, t, [], None, None)
    assert out["items"][0]["source"] == "forecast"


def test_agenda_is_empty_when_nothing_cleared_its_bar():
    out = vig.build_agenda([], [], [], None, None)
    assert out["items"] == []
    assert "no justifica una reunión" in out["empty_reason"]


def test_agenda_caps_and_reports_what_it_dropped():
    many = [_assessment("significant_down", delta=-9.0, label=f"M{i}") for i in range(8)]
    out = vig.build_agenda([], vig.tracker_signals(many), [], None, None)
    assert len(out["items"]) == vig.MAX_AGENDA_ITEMS
    assert out["dropped"] > 0
    assert "no prioriza nada" in out["note"]


def test_agenda_includes_divergence_when_present():
    reading = {"diverging": True, "direction": "converting_above_attitude",
               "delta_attitude": -3.0, "delta_behaviour": 1.3}
    out = vig.build_agenda([], [], [], reading, None)
    assert any(i["source"] == "category" for i in out["items"])


def test_agenda_groups_marginal_signals_as_one_low_priority_item():
    out = vig.build_agenda([], vig.tracker_signals([_assessment("marginal")]), [], None, None)
    low = [i for i in out["items"] if i["priority"] == vig.PRIORITY_LOW]
    assert len(low) == 1
    assert "corroboración" in low[0]["title"] or "corroboración" in low[0]["rationale"]


def test_macro_signals_are_contextual_and_sorted_worst_first():
    out = vig.macro_signals([_factor("favorable", "alto", "Buena"),
                             _factor("adverso", "alto", "Mala")])
    assert out[0].label == "Mala"
    assert all(s.strength == "contextual" for s in out)
