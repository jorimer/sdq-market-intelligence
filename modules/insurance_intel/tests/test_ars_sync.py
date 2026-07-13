"""Tests for the ARS (BDFINAC) ingest sync — offline, fixture mode.

Runs ``ars_sync(db, mode="fixture")`` against the committed real fixture
(``shared/data/fixtures/sisalril_ars.json``): roster + series + ISARS ratings are
created, the run is idempotent (a second pass upserts in place, no duplicates), and
the persisted rows mirror the fixture records exactly. No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.sisalril_ars_client import ARS_NAMES, SISALRILARSClient
import modules.insurance_intel.models.models as m
from modules.insurance_intel.ars_sync import ars_sync


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


def test_sync_creates_roster_series_and_ratings(db):
    res = ars_sync(db, mode="fixture")
    assert res["mode"] == "fixture" and res["source"] == "SISALRIL"
    # Roster: one entity per ARS in the fixture, all typed 'ars'.
    ents = db.query(m.InsuranceEntity).filter(m.InsuranceEntity.entity_type == "ars").all()
    assert len(ents) == res["ars"] == res["entities_created"]
    assert all(e.slug.startswith("ars_") and e.is_active for e in ents)
    # ISARS ratings written for the scored ARS.
    assert res["ratings_written"] > 0
    assert db.query(m.InsuranceRating).count() == res["ratings_written"]


def test_sync_is_idempotent(db):
    r1 = ars_sync(db, mode="fixture")
    n_series = db.query(m.InsuranceSeries).count()
    n_ents = db.query(m.InsuranceEntity).count()
    n_ratings = db.query(m.InsuranceRating).count()
    r2 = ars_sync(db, mode="fixture")
    assert r2["entities_created"] == 0                      # roster already seeded
    assert db.query(m.InsuranceSeries).count() == n_series  # upsert in place
    assert db.query(m.InsuranceEntity).count() == n_ents
    assert db.query(m.InsuranceRating).count() == n_ratings
    assert r1["series_rows"] == r2["series_rows"] == n_series


def test_rows_match_fixture_records(db):
    ars_sync(db, mode="fixture")
    recs = SISALRILARSClient(mode="fixture").fetch()
    assert recs, "fixture should yield records"
    # Fixture records are unique by (series, period, ars) → 1 DB row per record.
    assert db.query(m.InsuranceSeries).count() == len(recs)
    # Every persisted value equals its fixture record (spot-checked exhaustively).
    by_key = {(r.series, r.period, f"ars_{r.dimension}"): r.value for r in recs}
    for row in db.query(m.InsuranceSeries).all():
        assert row.value == by_key[(row.series_code, row.period, row.entity_slug)]
        assert row.source == "SISALRIL" and row.frequency == "monthly"


def test_roster_carries_official_names_and_upgrades_placeholders(db):
    ars_sync(db, mode="fixture")
    ents = {e.slug: e for e in db.query(m.InsuranceEntity).all()}
    # Official SISALRIL names (not coded placeholders) for known ARS_IDs.
    for ars_id, official in ARS_NAMES.items():
        slug = f"ars_{ars_id}"
        if slug in ents:
            assert ents[slug].name == official
    # A legacy coded placeholder is upgraded back to the official name on re-sync.
    ent = db.query(m.InsuranceEntity).filter(m.InsuranceEntity.slug == "ars_014").one()
    assert ent.name == ARS_NAMES["014"]
    ent.name = "ARS 014 (Privada)"
    db.commit()
    ars_sync(db, mode="fixture")
    refreshed = db.query(m.InsuranceEntity).filter(m.InsuranceEntity.slug == "ars_014").one()
    assert refreshed.name == ARS_NAMES["014"]
