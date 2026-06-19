"""Tests for the ENCFT employment sync (Gate-E PR-2).

Offline: the "live" fetch is routed to the committed ``encft_employment.json``
fixture, or made to raise, via monkeypatch. No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.encft_employment import EmploymentClient, EmploymentError
from shared.data.sector_crosswalk import ENCFT_BRANCHES
from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — register app_setting table
from modules.sector_intel.models.models import SectorVariable  # noqa: F401 — register tables
from modules.sector_intel.sectors_sync import LABOR_ENCFT_DIMENSION, encft_empleo_sync

BRANCH_KEYS = {b.key for b in ENCFT_BRANCHES}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _offline(monkeypatch):
    """Route the live fetch to the committed fixture (stays offline)."""
    monkeypatch.setattr(EmploymentClient, "_fetch_live", EmploymentClient._fetch_fixture)


def test_sync_persists_branches_with_provenance(db, monkeypatch):
    _offline(monkeypatch)
    res = encft_empleo_sync(db)
    assert res["errors"] == []
    assert res["synced"] > 0
    assert res["branches"] == 10
    assert res["variables"] == ["employment"]

    rows = db.query(SectorVariable).all()
    assert {r.sector_code for r in rows} == BRANCH_KEYS          # 10 ONE branches
    assert all(r.dimension == LABOR_ENCFT_DIMENSION for r in rows)
    assert all(r.variable == "employment" for r in rows)
    sample = db.query(SectorVariable).filter_by(sector_code="industrias").first()
    assert sample.source == "ONE" and sample.license  # real provenance stamped
    assert "2008" in res["periods"] and "2024" in res["periods"]


def test_sync_is_idempotent(db, monkeypatch):
    _offline(monkeypatch)
    first = encft_empleo_sync(db)
    n1 = db.query(SectorVariable).count()
    assert n1 == first["synced"]
    second = encft_empleo_sync(db)            # upsert in place — no duplicates
    assert db.query(SectorVariable).count() == n1
    assert second["synced"] == first["synced"]


def test_sync_best_effort_on_upstream_failure(db, monkeypatch):
    def _boom(self, series=None, period=None):
        raise EmploymentError("landing caída")
    monkeypatch.setattr(EmploymentClient, "_fetch_live", _boom)
    res = encft_empleo_sync(db)               # must NOT raise
    assert res["synced"] == 0
    assert res["errors"] and "landing caída" in res["errors"][0]
    assert db.query(SectorVariable).count() == 0   # nothing half-written


def test_employment_rows_do_not_pollute_the_iai(db, monkeypatch):
    """labor_encft branch rows must not leak into the 17-slug index or its periods."""
    from modules.sector_intel.service import (
        _sector_periods,
        assemble_iai_dataset,
        get_sector_variables,
    )

    # Real BCRD sector data for a single year (the index's true period grid).
    db.add(SectorVariable(sector_code="turismo", dimension="sector",
                          variable="sector_size", value=8.9, period="2024", source="BCRD"))
    db.commit()
    _offline(monkeypatch)
    encft_empleo_sync(db)                      # adds employment 2008-2024 under labor_encft

    # the index still sees ONLY the BCRD period, not 2008-2017 from employment
    assert _sector_periods(db) == ["2024"]
    # the index still assembles cleanly over the 17 slugs (sanity)
    assert len(assemble_iai_dataset(db)["dataset"]) == 17
    # get_sector_variables returns only sector-dimension inputs — no employment var,
    # no ONE branch key (the load-bearing check that the dimension filter works)
    sv = get_sector_variables(db)["sectors"]
    assert all("employment" not in vars_ for vars_ in sv.values())
    assert "industrias" not in sv
