"""Tests for the SISALRIL/CNSS SFS health-coverage ingest sync — offline, fixture mode.

Runs ``sisalril_sfs_sync(db, mode="fixture")`` against the committed real fixture
(``shared/data/fixtures/sisalril.json``): national SFS affiliation series are created
(no entity attribution), the run is idempotent, and rows mirror the fixture. No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.sisalril_client import SISALRILClient
import modules.insurance_intel.models.models as m
from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[
        m.InsuranceEntity.__table__, m.InsuranceSeries.__table__,
        m.InsuranceRating.__table__, m.InsuranceSnapshot.__table__])
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def test_sync_creates_sfs_series(db):
    res = sisalril_sfs_sync(db, mode="fixture")
    assert res["mode"] == "fixture" and res["source"] == "SISALRIL"
    assert res["sfs_rows"] > 0
    rows = db.query(m.InsuranceSeries).all()
    assert len(rows) == res["sfs_rows"]
    # National coverage series: never attributed to an entity.
    assert all(r.entity_slug is None for r in rows)
    codes = {r.series_code for r in rows}
    assert {"sfs.afiliacion.total", "sfs.afiliacion.contributivo",
            "sfs.afiliacion.subsidiado"} <= codes
    assert all(r.source == "SISALRIL" and r.frequency == "monthly" for r in rows)


def test_sync_is_idempotent(db):
    r1 = sisalril_sfs_sync(db, mode="fixture")
    n1 = db.query(m.InsuranceSeries).count()
    r2 = sisalril_sfs_sync(db, mode="fixture")
    n2 = db.query(m.InsuranceSeries).count()
    assert n1 == n2 == r1["sfs_rows"] == r2["sfs_rows"]


def test_rows_match_fixture_records(db):
    sisalril_sfs_sync(db, mode="fixture")
    recs = SISALRILClient(mode="fixture").fetch()
    assert recs, "fixture should yield records"
    by_key = {(r.series, r.period, r.dimension): r.value for r in recs}
    db_rows = db.query(m.InsuranceSeries).all()
    # Fixture records are unique by (series, period, dimension) → 1 DB row per record.
    assert len(db_rows) == len(by_key) == len(recs)
    for row in db_rows:
        assert row.value == by_key[(row.series_code, row.period, row.dimension)]
