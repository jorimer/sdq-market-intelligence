"""Tests for the Eje-1 backtest: discrimination metrics + outcome derivation."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
import shared.auth.models  # noqa: F401 — FK target
import modules.banking_score.models.models  # noqa: F401 — register tables
from modules.banking_score.models.models import BankingData, ModelType, RatingResult
from modules.banking_score.validation.metrics import (
    auc_low_score_risk, deterioration_rate_by_tier, gini, gini_bootstrap_ci,
)
from modules.banking_score.validation.outcomes_derivation import derive_observations
from modules.banking_score.validation.report import build_backtest_report


# ── Metrics: known Gini ─────────────────────────────────────────

def test_gini_perfect_discrimination_is_one():
    # Events (label 1) have the LOWEST scores → perfect risk ranking.
    scores = [10, 20, 30, 40, 50]
    labels = [1, 1, 0, 0, 0]
    assert auc_low_score_risk(scores, labels) == 1.0
    assert gini(scores, labels) == 1.0


def test_gini_inverted_is_minus_one():
    scores = [10, 20, 30, 40, 50]
    labels = [0, 0, 0, 1, 1]  # events have the HIGHEST scores → inverted
    assert gini(scores, labels) == -1.0


def test_gini_random_is_near_zero():
    scores = [10, 20, 30, 40]
    labels = [1, 0, 0, 1]  # events at the extremes → no net discrimination
    assert gini(scores, labels) == 0.0


def test_gini_ties_count_as_half():
    scores = [10, 10, 20, 20]
    labels = [1, 0, 1, 0]
    # event@10 vs non@10 (tie .5) + event@10 vs non@20 (1) ; event@20 vs non@10 (0) + vs non@20 (.5)
    # total = .5+1+0+.5 = 2 over 2*2=4 → AUC .5 → gini 0
    assert gini(scores, labels) == 0.0


def test_gini_none_when_single_class():
    assert gini([1, 2, 3], [0, 0, 0]) is None
    assert gini([1, 2, 3], [1, 1, 1]) is None


def test_bootstrap_ci_brackets_point_estimate():
    scores = list(range(40))
    labels = [1 if i < 12 else 0 for i in range(40)]  # low scores deteriorate
    g, lo, hi = gini_bootstrap_ci(scores, labels, n_boot=300, seed=1)
    assert g is not None and lo is not None and hi is not None
    assert lo <= g <= hi
    assert g > 0.8  # strong discrimination


def test_deterioration_rate_by_tier_monotonic_flag():
    order = ["SDQ-AAA", "SDQ-AA", "SDQ-A", "SDQ-D"]
    tiers = ["SDQ-AAA"] * 4 + ["SDQ-AA"] * 4 + ["SDQ-A"] * 4 + ["SDQ-D"] * 4
    labels = [0, 0, 0, 0] + [1, 0, 0, 0] + [1, 1, 0, 0] + [1, 1, 1, 1]  # 0, .25, .5, 1
    rows, monotonic = deterioration_rate_by_tier(tiers, labels, order)
    assert [round(r["rate"], 2) for r in rows] == [0.0, 0.25, 0.5, 1.0]
    assert monotonic is True


def test_deterioration_rate_non_monotonic_detected():
    order = ["SDQ-AAA", "SDQ-AA", "SDQ-D"]
    tiers = ["SDQ-AAA", "SDQ-AA", "SDQ-D"]
    labels = [1, 0, 0]  # best tier deteriorates, worst doesn't → NOT monotonic
    _, monotonic = deterioration_rate_by_tier(tiers, labels, order)
    assert monotonic is False


# ── Outcome derivation ──────────────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _rate(db, bank, period, score, tier):
    db.add(RatingResult(bank_id=bank, period_end=period, overall_score=score,
                        rating_tier=tier, model_type=ModelType.deterministic))


PERIODS = [date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30),
           date(2024, 12, 31), date(2025, 3, 31)]


def test_relative_notch_downgrade_does_not_trigger(db):
    # A ≥2-notch tier drop alone must NOT count as deterioration (floor/ceiling
    # artifact — only financial distress counts).
    _rate(db, "B1", PERIODS[0], 86, "SDQ-AA")
    _rate(db, "B1", PERIODS[1], 72, "SDQ-A")  # 3-notch drop, no financial distress
    _rate(db, "B1", PERIODS[2], 72, "SDQ-A")
    db.commit()
    obs = {o.period_end: o for o in derive_observations(db)}
    assert obs[PERIODS[0]].deteriorated is False
    # last period has no horizon → not observed
    assert PERIODS[2] not in obs


def test_stable_bank_not_deteriorated(db):
    for p in PERIODS:
        _rate(db, "B2", p, 86, "SDQ-AA")
    db.commit()
    obs = derive_observations(db)
    assert all(o.deteriorated is False for o in obs)
    assert all(not o.triggers for o in obs)


def test_solvency_breach_marks_deterioration(db):
    _rate(db, "B3", PERIODS[0], 80, "SDQ-AA-")
    _rate(db, "B3", PERIODS[1], 80, "SDQ-AA-")
    db.add(BankingData(bank_id="B3", period_end=PERIODS[1], solvencia_pct=8.0,
                       activos_totales=100, utilidad_neta=5))
    db.commit()
    obs = {o.period_end: o for o in derive_observations(db)}
    assert obs[PERIODS[0]].deteriorated is True
    assert "solvencia_breach" in obs[PERIODS[0]].triggers


def test_morosidad_doubling_marks_deterioration(db):
    _rate(db, "B4", PERIODS[0], 80, "SDQ-AA-")
    _rate(db, "B4", PERIODS[1], 80, "SDQ-AA-")
    db.add(BankingData(bank_id="B4", period_end=PERIODS[0], morosidad_pct=2.0,
                       activos_totales=100, utilidad_neta=5))
    db.add(BankingData(bank_id="B4", period_end=PERIODS[1], morosidad_pct=4.5,
                       activos_totales=100, utilidad_neta=5))
    db.commit()
    obs = {o.period_end: o for o in derive_observations(db)}
    assert obs[PERIODS[0]].deteriorated is True
    assert "morosidad_x2" in obs[PERIODS[0]].triggers


def test_report_end_to_end(db):
    # One bank that hits financial distress + several stable → report computes.
    _rate(db, "BAD", PERIODS[0], 50, "SDQ-BBB")
    _rate(db, "BAD", PERIODS[1], 48, "SDQ-BBB")
    db.add(BankingData(bank_id="BAD", period_end=PERIODS[1], solvencia_pct=7.0,
                       activos_totales=100, utilidad_neta=-5))
    for k in range(5):
        for p in PERIODS:
            _rate(db, f"OK{k}", p, 88, "SDQ-AA")
    db.commit()
    rep = build_backtest_report(db, n_boot=100)
    assert rep["ok"] is True
    assert rep["n_observations"] > 0
    assert rep["n_events"] >= 1
    assert any("preliminar" in c.lower() for c in rep["caveats"])
    assert isinstance(rep["by_tier"], list)
