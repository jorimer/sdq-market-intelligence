"""Service and report tests: engagement isolation, analysis over the DB, and the
report's auto-generated methodology, sources and limits.

The isolation tests matter most. This is the platform's only module holding private
per-client data, so "another client cannot see this" is a correctness property, not a
preference.
"""
import pytest

from modules.brand_intel import report as rpt
from modules.brand_intel import service as svc
from modules.brand_intel.models.models import (
    BrandDecision,
    BrandEngagement,
    BrandForecast,
    BrandObservation,
    BrandWave,
)


# ── isolation ─────────────────────────────────────────────────────────

def test_staff_can_access_any_engagement(engagement):
    assert svc.can_access(engagement, organization_id=None, is_staff=True)


def test_engagement_without_org_is_staff_only(engagement):
    """An unassigned mandate must never become world-readable by accident."""
    assert not svc.can_access(engagement, organization_id="org-1", is_staff=False)


def test_other_organization_is_denied(db, engagement):
    engagement.organization_id = "org-1"
    db.commit()
    assert svc.can_access(engagement, organization_id="org-1", is_staff=False)
    assert not svc.can_access(engagement, organization_id="org-2", is_staff=False)


def test_list_engagements_filters_by_organization(db, engagement):
    engagement.organization_id = "org-1"
    db.add(BrandEngagement(slug="otro", client_name="Otro", focal_brand="X",
                           market="RD", organization_id="org-2"))
    db.commit()
    assert [e.slug for e in svc.list_engagements(db, "org-1")] == ["demo"]
    assert len(svc.list_engagements(db, None)) == 2


# ── waves ─────────────────────────────────────────────────────────────

def test_data_waves_excludes_a_projection_wave(db, engagement):
    """A future wave created to hold a frozen forecast must not become 'the latest wave'
    and leave every reading pointing at an empty column."""
    db.add(BrandWave(engagement_id=engagement.id, code="w4", label="Ola 4",
                     sort_order=4, is_projection=True))
    db.commit()
    assert len(svc.waves(db, engagement.id)) == 4
    assert [w.code for w in svc.data_waves(db, engagement.id)] == ["w1", "w2", "w3"]


# ── category ──────────────────────────────────────────────────────────

def test_category_analysis_uses_only_in_set_brands(db, engagement):
    out = svc.category_analysis(db, engagement.id)
    assert out["available"]
    # focal 40 + rival 60 = 100 每 wave; the out-of-set brand is excluded
    assert [r["value"] for r in out["category_size"]] == [100.0, 100.0, 100.0]
    assert {b["brand"] for b in out["share"]} == {"focal", "rival"}


def test_category_growth_is_flat_on_the_fixture(db, engagement):
    assert svc.category_analysis(db, engagement.id)["category_growth_pct"] == pytest.approx(0.0)


def test_divergence_is_detected_on_the_fixture(db, engagement):
    """Fixture is built so preference falls (32→28) while traffic share rises (35→45)."""
    reading = svc.category_analysis(db, engagement.id)["divergence_reading"]
    assert reading["diverging"] is True
    assert reading["direction"] == "converting_above_attitude"


def test_category_unavailable_without_reach_observations(db, engagement):
    db.query(BrandObservation).filter(
        BrandObservation.metric_code == "reach_7d").delete()
    db.commit()
    out = svc.category_analysis(db, engagement.id)
    assert not out["available"]
    assert "denominador" in out["reason"]


def test_attribution_decomposes_the_last_step(db, engagement):
    out = svc.attribution_analysis(db, engagement.id)
    assert out["available"]
    reach = next(r for r in out["rows"] if r["metric_code"] == "reach_7d")
    assert reach["delta"] == pytest.approx(10.0)             # 35 → 45
    assert reach["category_effect"] == pytest.approx(0.0)    # flat category
    assert reach["brand_effect"] == pytest.approx(10.0)
    assert reach["verdict"] == "marca"


# ── ticket / deflation ────────────────────────────────────────────────

def test_ticket_unavailable_without_observations(db, engagement):
    out = svc.ticket_analysis(db, engagement.id)
    assert not out["available"]


def test_ticket_stays_nominal_without_an_inflation_series(db, engagement):
    """No macro series must yield a declared nominal reading, never a silent deflation."""
    wave_ids = engagement.wave_ids
    for code, value in [("w1", 1000), ("w2", 1050), ("w3", 1100)]:
        db.add(BrandObservation(
            engagement_id=engagement.id, wave_id=wave_ids[code], brand_slug="focal",
            metric_code="ticket_avg", segment="total", value=value, base_n=300, unit="RD$"))
    db.commit()
    out = svc.ticket_analysis(db, engagement.id)
    assert out["available"] and out["deflated"] is False
    assert "NOMINAL" in out["reason"]


# ── forecasting ───────────────────────────────────────────────────────

def test_issue_forecast_uses_one_pooled_rule_for_every_metric(db, engagement):
    db.add(BrandWave(engagement_id=engagement.id, code="w4", label="Ola 4",
                     sort_order=4, is_projection=True))
    db.commit()
    out = svc.issue_forecasts(db, engagement.id, "w4")
    db.commit()
    assert out["issued"]
    assert len({f["rule"] for f in out["issued"]}) == 1


def test_issue_forecast_rejects_an_unknown_target_wave(db, engagement):
    assert "no existe" in svc.issue_forecasts(db, engagement.id, "w9")["error"]


def test_scoring_marks_inside_band_and_never_reseeds(db, engagement):
    db.add(BrandForecast(
        engagement_id=engagement.id, target_wave_id=engagement.wave_ids["w3"],
        brand_slug="focal", metric_code="reach_7d", segment="total",
        point=44.0, lo=38.0, hi=50.0, rule="mean",
        issued_at_wave_id=engagement.wave_ids["w2"], status="pending"))
    db.commit()

    out = svc.score_pending_forecasts(db, engagement.id)
    db.commit()
    assert out["n"] == 1
    assert out["scored"][0]["actual"] == 45.0
    assert out["scored"][0]["inside_band"] is True
    # Already scored: a second pass must not re-score it.
    assert svc.score_pending_forecasts(db, engagement.id)["n"] == 0


def test_track_record_reports_absence_before_the_first_scored_forecast(db, engagement):
    out = svc.forecast_track_record(db, engagement.id)
    assert not out["available"]
    assert "track record" in out["reason"]


# ── signal filter and ledger ──────────────────────────────────────────

def test_signal_filter_returns_thresholds_for_the_focal_brand(db, engagement):
    out = svc.signal_filter(db, engagement.id)
    assert out["available"]
    codes = {r["metric_code"] for r in out["rows"]}
    assert "reach_7d" in codes
    assert all(r["threshold"] is not None for r in out["rows"] if r["publishable"])


def test_feasibility_check_blocks_an_undetectable_decision(db, engagement):
    out = svc.check_decision_feasibility(
        db, engagement.id, "reach_7d", "focal", "total",
        engagement.wave_ids["w2"], success_threshold=1.0)
    assert not out["feasible"]
    assert "inevaluable" in out["reason"]


def test_decision_verdict_written_back_to_the_row(db, engagement):
    db.add(BrandDecision(
        engagement_id=engagement.id, title="Subir alcance",
        metric_code="reach_7d", segment="total", brand_slug="focal",
        baseline_wave_id=engagement.wave_ids["w2"],
        target_wave_id=engagement.wave_ids["w3"],
        success_threshold=8.0, owner="Marketing", status="open"))
    db.commit()

    out = svc.evaluate_decisions(db, engagement.id)
    db.commit()
    assert out["summary"]["total"] == 1
    row = db.query(BrandDecision).one()
    assert row.status == out["decisions"][0]["status"]
    assert row.observed_delta == pytest.approx(10.0)   # 35 → 45


# ── S3 / S4 / S5 over the database ────────────────────────────────────

def test_macro_context_degrades_to_unknown_without_a_contract(db, engagement):
    """No published contract must read as 'unknown', never as a benign 'neutral'."""
    out = svc.macro_context(db)
    assert out["available"] is False
    assert out["stance"] == "desconocido"


def test_attribution_covers_every_core_indicator_with_data(db, engagement):
    out = svc.attribution_analysis(db, engagement.id)
    assert out["available"]
    codes = {r["metric_code"] for r in out["rows"]}
    assert "reach_7d" in codes and "favourite_place" in codes


def test_attribution_splits_reach_but_not_preference(db, engagement):
    rows = {r["metric_code"]: r for r in svc.attribution_analysis(db, engagement.id)["rows"]}
    assert rows["reach_7d"]["category_effect"] is not None
    assert rows["favourite_place"]["category_effect"] is None


def test_scenarios_available_and_carry_no_probabilities(db, engagement):
    out = svc.scenarios_analysis(db, engagement.id)
    assert out["available"]
    assert out["scenarios"]
    assert all("band_reading" in s for s in out["scenarios"])


def test_scenarios_report_rule_dispersion_per_metric(db, engagement):
    out = svc.scenarios_analysis(db, engagement.id)
    assert out["rule_dispersion"]
    assert all("spread" in d and "robust" in d for d in out["rule_dispersion"])


def test_scenarios_risks_always_include_the_instrument_warning(db, engagement):
    names = {r["risk"] for r in svc.scenarios_analysis(db, engagement.id)["risks"]}
    assert "Cambio de instrumento" in names


def test_vigilance_builds_signals_and_agenda(db, engagement):
    out = svc.vigilance_analysis(db, engagement.id)
    assert out["available"]
    assert set(out["signals"]) == {"macro", "tracker", "forecast", "decision"}
    assert "items" in out["agenda"]


def test_vigilance_surfaces_the_divergence_in_the_agenda(db, engagement):
    """The fixture diverges by construction, so it must reach the agenda."""
    out = svc.vigilance_analysis(db, engagement.id)
    assert any(i["source"] == "category" for i in out["agenda"]["items"])


def test_vigilance_keeps_only_movements_that_clear_their_threshold(db, engagement):
    """Reach moves 35 → 45 (10 pp over a ~7.8 pp threshold) and must survive; preference
    moves 32 → 28 (4 pp, under its threshold) and must be dropped entirely."""
    out = svc.vigilance_analysis(db, engagement.id)
    labels = {s["label"] for s in out["signals"]["tracker"]}
    assert any("7 días" in lab for lab in labels)
    assert not any("favorito" in lab for lab in labels)


# ── report ────────────────────────────────────────────────────────────

def test_report_builds_every_section(db, engagement):
    p = rpt.build_report(db, engagement)
    assert set(p["sections"]) == {
        "explanations", "category", "funnel", "ticket", "attribution",
        "forecast_backtest", "forecast_track_record", "signal_filter", "decisions",
        "scenarios", "vigilance", "plan",
    }
    assert p["engagement"]["focal_brand"] == "Focal"


def test_report_limits_are_generated_from_the_analysis_state(db, engagement):
    """Limits are derived, not written: with three waves the report must say the forecast
    is a naive baseline, and it must always deny causality and AI-estimated figures."""
    p = rpt.build_report(db, engagement)
    joined = " ".join(p["limits"])
    assert "línea base ingenua" in joined
    assert "causalidad" in joined
    assert "Ninguna cifra fue estimada por IA" in joined


def test_report_executive_leads_with_what_only_sdq_adds(db, engagement):
    """El resumen ya no lidera con share/divergencia/embudo — re-análisis del dato del
    proveedor. Sin conclusiones utilizables ni entorno, lo honesto es decirlo."""
    ex = rpt.build_report(db, engagement)["executive"]
    titles = [f["title"] for f in ex["findings"]]
    assert not any("cruzan" in t for t in titles)
    if not ex["findings"]:
        assert "conclusiones del proveedor" in ex["empty_reason"]


def test_report_caps_the_executive_at_three_findings(db, engagement):
    assert len(rpt.build_report(db, engagement)["executive"]["findings"]) <= 3


def test_report_renders_valid_html(db, engagement):
    html = rpt.render_html(rpt.build_report(db, engagement))
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "Informe de Contexto de Mercado" in html
    assert "Límites declarados" in html


def test_report_states_missing_sections_instead_of_hiding_them(db, engagement):
    """A section that silently disappears reads as an absence of problems."""
    html = rpt.render_html(rpt.build_report(db, engagement))
    assert "El ticket en pesos constantes" in html
    assert "empty" in html          # the ticket section renders its stated reason


def test_category_refuses_a_denominator_of_one_brand(db, engagement):
    """A share against a one-member category is 100% by construction, not a finding."""
    from modules.brand_intel.models.models import BrandObservation, BrandWave

    db.query(BrandObservation).filter(
        BrandObservation.engagement_id == engagement.id).delete()
    wave = db.query(BrandWave).filter(
        BrandWave.engagement_id == engagement.id).order_by(BrandWave.sort_order).first()
    for value in (27.0, 25.0):
        db.add(BrandObservation(
            engagement_id=engagement.id, wave_id=wave.id, brand_slug="focal",
            metric_code=svc.REACH_METRIC, segment="total", value=value, base_n=300,
        ))
        break
    db.commit()

    out = svc.category_analysis(db, engagement.id)
    assert out["available"] is False
    assert "no es una categoría" in out["reason"]
