"""Tests for trade_intel persistence and events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.trade_intel.events import TRADE_UPDATED
from modules.trade_intel.models.models import (  # noqa: F401 — register tables
    TradeFlow,
    TradeScore,
)
from modules.trade_intel.service import (
    compute_and_persist,
    get_flows,
    get_latest_score,
)

FLOWS = [
    {"product": "A", "direction": "export", "value": 60.0, "source": "BCRD"},
    {"product": "B", "direction": "export", "value": 40.0, "source": "BCRD"},
    {"product": "oil", "direction": "import", "value": 50.0, "source": "BCRD"},
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_bus():
    event_bus.clear()
    yield
    event_bus.clear()


def test_persists_flows_and_score(db):
    res = compute_and_persist(db, "2025", FLOWS)
    assert "score_id" in res
    assert db.query(TradeFlow).count() == 3
    score = db.query(TradeScore).one()
    assert score.resilience_score == res["resilience_score"]


def test_publishes_trade_updated(db):
    received = []
    event_bus.subscribe(TRADE_UPDATED, lambda p: received.append(p))
    compute_and_persist(db, "2025", FLOWS)
    assert len(received) == 1
    assert received[0]["period"] == "2025"
    assert "resilience_score" in received[0]


def test_idempotent_per_period(db):
    compute_and_persist(db, "2025", FLOWS)
    compute_and_persist(db, "2025", FLOWS)
    assert db.query(TradeScore).count() == 1
    assert db.query(TradeFlow).count() == 3  # replaced, not duplicated


def test_empty_flows_raises(db):
    with pytest.raises(ValueError):
        compute_and_persist(db, "2025", [])


def test_getters(db):
    compute_and_persist(db, "2025", FLOWS)
    assert get_latest_score(db).period == "2025"
    assert len(get_flows(db, "2025")) == 3
