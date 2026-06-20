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
    """IAI and next-year employment growth perfectly rank-aligned → Spearman ≈ 1."""
    # sector_growth is a non-monotonic permutation (not rank-aligned with the IAI),
    # so the partial correlation is well-defined (denominator != 0).
    growth_perm = [3.0, 6.0, 2.0, 5.0, 1.0, 4.0, 0.0]
    for i, (branch, slug) in enumerate(_PAIRS, start=1):
        _score(db, slug, "2018", iai=10.0 * i)
        _var(db, slug, "sector_size", 1.0, "2018")
        _var(db, slug, "sector_growth", growth_perm[i - 1], "2018")
        _emp(db, branch, 1000.0, "2018")
        _emp(db, branch, 1000.0 * (1 + 2 * i / 100.0), "2019")   # growth = 2·i %
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
    assert rep["n_observations"] == 7
    assert rep["spearman"] == pytest.approx(1.0)         # perfect rank alignment
    assert rep["quintile_spread"]["spread"] > 0
    assert rep["spearman_partial_growth"] is not None    # control computed


def test_gate_e_report_honest_when_insufficient(db):
    _score(db, "comercio", "2018", 50.0)         # no employment, no lookahead
    db.commit()
    rep = gate_e_report(db)
    assert rep["has_data"] is False and "reason" in rep
