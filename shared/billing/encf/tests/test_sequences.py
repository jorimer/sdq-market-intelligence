"""Tests de asignación de secuencias e-NCF (rangos autorizados DGII)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.billing.models  # noqa: F401
from shared.billing.encf.sequences import (
    EncfSequenceError,
    allocate_next,
    format_encf,
    list_sequences,
    upsert_sequence,
)
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_format_encf():
    assert format_encf("31", 1) == "E310000000001"
    assert format_encf("46", 12345) == "E460000012345"


def test_allocate_consecutive(db):
    upsert_sequence(db, ecf_type="31", range_from=1, range_to=5)
    assert allocate_next(db, "31")["encf"] == "E310000000001"
    assert allocate_next(db, "31")["encf"] == "E310000000002"
    assert allocate_next(db, "31")["encf"] == "E310000000003"


def test_allocate_raises_when_not_configured(db):
    with pytest.raises(EncfSequenceError):
        allocate_next(db, "32")


def test_allocate_raises_when_exhausted(db):
    upsert_sequence(db, ecf_type="31", range_from=1, range_to=1)
    assert allocate_next(db, "31")["encf"] == "E310000000001"
    with pytest.raises(EncfSequenceError):
        allocate_next(db, "31")


def test_allocate_raises_when_expired(db):
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    upsert_sequence(db, ecf_type="46", range_from=1, range_to=100, expires_at=past)
    with pytest.raises(EncfSequenceError):
        allocate_next(db, "46")


def test_upsert_updates_active_row(db):
    upsert_sequence(db, ecf_type="31", range_from=1, range_to=5)
    upsert_sequence(db, ecf_type="31", range_from=1, range_to=50)  # amplía el rango
    seqs = [s for s in list_sequences(db) if s["ecf_type"] == "31"]
    assert len(seqs) == 1 and seqs[0]["range_to"] == "50" and seqs[0]["remaining"] == 50


def test_upsert_rejects_bad_range(db):
    with pytest.raises(EncfSequenceError):
        upsert_sequence(db, ecf_type="31", range_from=100, range_to=10)


def test_list_reports_status(db):
    upsert_sequence(db, ecf_type="32", range_from=1, range_to=3)
    allocate_next(db, "32")
    row = [s for s in list_sequences(db) if s["ecf_type"] == "32"][0]
    assert row["current"] == "2" and row["remaining"] == 2 and row["next_encf"] == "E320000000002"
