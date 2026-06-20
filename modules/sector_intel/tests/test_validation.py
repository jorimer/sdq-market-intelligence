"""Tests for the Gate-E sectorial backtest harness."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.sector_intel.models.models import SectorScore, SectorVariable  # noqa: F401
from modules.sector_intel.validation.historical import build_iai_panel
from modules.sector_intel.validation.outcomes import employment_by_branch, label_panel
from modules.sector_intel.validation.report import gate_e_report

# 7 single-member branches (branch_key == its one slug's branch) for a clean panel.
_PAIRS = [("agricultura", "agropecuario"), ("energia", "energia"),
          ("construccion", "construccion"), ("comercio", "comercio"),
          ("turismo", "turismo"), ("financiero", "financiero"),
          ("administracion_publica", "administracion_publica")]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _score(db, slug, period, iai):
    db.add(SectorScore(sector_code=slug, period=period, iai_score=iai, model_version="1.0"))


def _var(db, slug, var, value, period):
    db.add(SectorVariable(sector_code=slug, dimension="sector", variable=var,
                          value=value, period=period, source="BCRD"))


def _emp(db, branch, value, period):
    db.add(SectorVariable(sector_code=branch, dimension="labor_encft",
                          variable="employment", value=value, period=period, source="ONE"))


def _seed_monotonic(db):
    """IAI and next-year employment growth rank-aligned in TWO years → yearly IC ≈ 1.

    Seeds a coherent employment series (2018→2019→2020 each +2·i %) so BOTH year-pairs
    rank monotonically with the IAI, giving a per-year IC series (n_years=2) for the
    mean-IC headline — not just a single stacked cross-section.
    """
    # sector_growth is a non-monotonic permutation (not rank-aligned with the IAI),
    # so the partial correlation is well-defined (denominator != 0).
    growth_perm = [3.0, 6.0, 2.0, 5.0, 1.0, 4.0, 0.0]
    for i, (branch, slug) in enumerate(_PAIRS, start=1):
        g = 1 + 2 * i / 100.0
        _emp(db, branch, 1000.0, "2018")
        _emp(db, branch, 1000.0 * g, "2019")          # 2018→2019 growth = 2·i %
        _emp(db, branch, 1000.0 * g * g, "2020")      # 2019→2020 growth = 2·i %
        for period in ("2018", "2019"):
            _score(db, slug, period, iai=10.0 * i)
            _var(db, slug, "sector_size", 1.0, period)
            _var(db, slug, "sector_growth", growth_perm[i - 1], period)
    db.commit()


def test_panel_aggregates_iai_weighted_by_size(db):
    # bundle branch "industrias" = manufactura_local + zonas_francas + mineria
    _score(db, "manufactura_local", "2018", 60.0)
    _score(db, "zonas_francas", "2018", 40.0)
    _score(db, "mineria", "2018", 20.0)
    _var(db, "manufactura_local", "sector_size", 3.0, "2018")
    _var(db, "zonas_francas", "sector_size", 1.0, "2018")
    _var(db, "mineria", "sector_size", 1.0, "2018")
    db.commit()
    panel = build_iai_panel(db)
    ind = next(r for r in panel if r["branch"] == "industrias" and r["period"] == "2018")
    assert ind["iai_score"] == pytest.approx((60 * 3 + 40 + 20) / 5)   # = 48.0


def test_label_panel_drops_rows_without_lookahead(db):
    _seed_monotonic(db)
    _emp(db, "comercio", 999.0, "2018")     # comercio has 2018 but we'll remove its 2019
    db.commit()
    # remove comercio's 2019 employment → no lookahead for that branch-period
    db.query(SectorVariable).filter_by(sector_code="comercio", period="2019").delete()
    db.commit()
    panel = build_iai_panel(db)
    labeled = label_panel(panel, employment_by_branch(db))
    branches = {r["branch"] for r in labeled}
    assert "comercio" not in branches           # dropped, not fabricated
    assert "turismo" in branches


def test_gate_e_report_recovers_monotonic_signal(db):
    _seed_monotonic(db)
    rep = gate_e_report(db)
    assert rep["has_data"] is True
    assert rep["n_observations"] == 14                   # 7 branches × 2 year-pairs
    assert rep["n_years"] == 2
    # HEADLINE: mean yearly IC detects the signal (both years rank-align → IC≈1)
    assert rep["mean_yearly_ic"] == pytest.approx(1.0)
    assert rep["ic_ci"][0] == pytest.approx(1.0)         # CI excludes zero (point at 1.0)
    # SECONDARY: the pooled stacked Spearman is still reported, labeled
    assert rep["spearman_pooled"] == pytest.approx(1.0)
    assert "spearman_pooled_note" in rep
    assert rep["quintile_spread"]["spread"] > 0
    assert rep["spearman_partial_growth"] is not None    # control computed, intact


def test_gate_e_report_reports_noise_without_massaging(db):
    """Signal flips sign across years → mean IC ≈ 0, CI crosses zero, shown as-is."""
    for i, (branch, slug) in enumerate(_PAIRS, start=1):
        _emp(db, branch, 1000.0, "2018")
        _emp(db, branch, 1000.0 * (1 + 2 * i / 100.0), "2019")    # 2018 IC = +1 (rank↑)
        # 2019→2020 growth = 2·(8−i)% → ranks OPPOSITE to the IAI → 2019 IC = −1
        _emp(db, branch, 1000.0 * (1 + 2 * i / 100.0) * (1 + 2 * (8 - i) / 100.0), "2020")
        for period in ("2018", "2019"):
            _score(db, slug, period, iai=10.0 * i)
            _var(db, slug, "sector_size", 1.0, period)
    db.commit()
    rep = gate_e_report(db)
    assert rep["has_data"] is True
    assert rep["mean_yearly_ic"] == pytest.approx(0.0, abs=0.05)  # +1 and −1 average to 0
    assert rep["ic_ci"][0] < 0 < rep["ic_ci"][1]                 # CI spans zero, honest


def test_gate_e_report_honest_when_insufficient(db):
    _score(db, "comercio", "2018", 50.0)         # no employment, no lookahead
    db.commit()
    rep = gate_e_report(db)
    assert rep["has_data"] is False and "reason" in rep
