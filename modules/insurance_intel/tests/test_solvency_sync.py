"""Tests for the SIS solvency/liquidity ingest sync — offline, fixture mode.

Covers the pure roster matcher ``_match_slug`` (exact / prefix normalization / unique
first-token / no-match) and ``solvency_sync(db, mode="fixture")`` against the committed
real fixture (``shared/data/fixtures/sis_solvency.json``): entity matching + creation,
per-entity regulatory index series, idempotency and official-name upgrade. No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.sis_solvency_client import SISSolvencyClient, brand_key
import modules.insurance_intel.models.models as m
from modules.insurance_intel.solvency_sync import _match_slug, solvency_sync


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


# ── _match_slug (pure) ────────────────────────────────────────────
def test_match_slug_exact():
    existing = {"universal": "universal", "banreservas": "banreservas"}
    assert _match_slug("universal", existing) == "universal"


def test_match_slug_prefix_both_directions():
    # Existing key is a truncated sheet name; the solvency key is the full brand.
    assert _match_slug("angloamericana", {"angloameri": "angloamericana"}) == "angloamericana"
    # And the reverse: the solvency key is shorter than the roster key.
    assert _match_slug("angloameri", {"angloamericana": "angloamericana"}) == "angloamericana"


def test_match_slug_prefix_requires_five_chars():
    # A short shared prefix must NOT match (anti "BON"∈"BONAO" substring lesson).
    assert _match_slug("bona", {"bonanza": "bonanza"}) is None


def test_match_slug_unique_first_token():
    existing = {"mapfre_bhd": "mapfre_bhd"}
    assert _match_slug("mapfre_salud", existing) == "mapfre_bhd"
    # Ambiguous first token (two candidates) → no confident match.
    existing["mapfre_vida"] = "mapfre_vida"
    assert _match_slug("mapfre_salud", existing) is None


def test_match_slug_no_match_returns_none():
    assert _match_slug("atlantica", {"universal": "universal"}) is None
    assert _match_slug("atlantica", {}) is None


def test_match_slug_normalized_names_meet_at_the_key():
    # brand_key strips corporate/generic tokens, so differently-styled names of the
    # same insurer normalize to the same key and match exactly.
    a = brand_key("Angloamericana de Seguros, S. A.")
    b = brand_key("ANGLOAMERICANA DE SEGUROS")
    assert a == b
    assert _match_slug(a, {b: "angloamericana"}) == "angloamericana"


# ── solvency_sync (fixture mode) ──────────────────────────────────
def test_sync_creates_entities_and_series_from_fixture(db):
    res = solvency_sync(db, mode="fixture")
    recs = SISSolvencyClient(mode="fixture").fetch()
    assert res["mode"] == "fixture" and res["records"] == len(recs)
    # Empty roster → every insurer in the fixture is created exactly once (the second
    # record of each pair resolves via seen_new, so no duplicate entities).
    n_entities = len({r.dimension for r in recs})
    assert res["entities_created"] == n_entities
    assert db.query(m.InsuranceEntity).count() == n_entities
    # Two index series (solvencia + liquidez) per insurer, values as in the fixture.
    assert res["series_rows"] == len(recs)
    assert db.query(m.InsuranceSeries).count() == len(recs)
    by_name = {(r.series, r.dimension): r.value for r in recs}
    ents = {e.slug: e.name for e in db.query(m.InsuranceEntity).all()}
    for row in db.query(m.InsuranceSeries).all():
        assert row.value == by_name[(row.series_code, ents[row.entity_slug])]
        assert row.frequency == "quarterly" and row.source == "SIS"


def test_sync_is_idempotent(db):
    solvency_sync(db, mode="fixture")
    n_ents = db.query(m.InsuranceEntity).count()
    n_series = db.query(m.InsuranceSeries).count()
    res2 = solvency_sync(db, mode="fixture")
    # Second run matches everything it created before — no new rows.
    assert res2["entities_created"] == 0
    assert res2["entities_matched"] == n_ents
    assert db.query(m.InsuranceEntity).count() == n_ents
    assert db.query(m.InsuranceSeries).count() == n_series


def test_sync_matches_existing_roster_and_upgrades_name(db):
    # Seed a roster entity with a truncated audited-sheet name (real insurer).
    db.add(m.InsuranceEntity(slug="angloamericana", name="Angloamericana",
                             entity_type="aseguradora", is_active=True))
    db.flush()
    res = solvency_sync(db, mode="fixture")
    assert res["entities_matched"] >= 1
    ent = db.query(m.InsuranceEntity).filter(m.InsuranceEntity.slug == "angloamericana").one()
    # Name upgraded to the longer official published name.
    assert len(ent.name) > len("Angloamericana") and "Angloamericana" in ent.name
    # The regulatory indices landed on the EXISTING slug (no duplicate entity).
    rows = db.query(m.InsuranceSeries).filter(
        m.InsuranceSeries.entity_slug == "angloamericana").all()
    assert {r.series_code for r in rows} == {"indice_solvencia", "indice_liquidez"}
