"""Tests for social_dev: development index, distribution, persistence, events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.social_dev.events import SOCIAL_UPDATED
from modules.social_dev.models.models import (  # noqa: F401 — register tables
    DevelopmentScore,
    SocialIndicator,
)
from modules.social_dev.scoring.development import (
    IDM_CONFIG,
    compute_development,
    distribution_stats,
)
from modules.social_dev.service import compute_and_persist, get_latest

DATASET = {
    "nacional": {"life_expectancy": 74, "child_mortality": 28, "literacy_rate": 94,
                 "schooling_years": 9, "income_per_capita": 9000, "poverty_rate": 23,
                 "financial_inclusion": 56, "informality_rate": 55},
    "santo_domingo": {"life_expectancy": 76, "child_mortality": 22, "literacy_rate": 96,
                      "schooling_years": 11, "income_per_capita": 12000, "poverty_rate": 18,
                      "financial_inclusion": 65, "informality_rate": 48},
    "sur_profundo": {"life_expectancy": 70, "child_mortality": 40, "literacy_rate": 88,
                     "schooling_years": 6, "income_per_capita": 5000, "poverty_rate": 38,
                     "financial_inclusion": 40, "informality_rate": 70},
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
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


def test_weights_sum_to_one():
    assert round(sum(IDM_CONFIG.dimension_weights.values()), 6) == 1.0


def test_development_in_range_and_inverts_risk():
    res = compute_development("santo_domingo", DATASET)
    assert 0.0 <= res["development_score"] <= 100.0
    # santo_domingo has lowest poverty → inverted → best (100)
    pov = res["dimensions"]["living_standards"]["variables"]["poverty_rate"]
    assert pov["inverted"] is True
    assert pov["normalized"] == 100.0


def test_distribution_reports_spread_not_just_mean():
    stats = distribution_stats([40.0, 60.0, 80.0])
    assert stats["mean"] == 60.0
    assert stats["spread"] == 40.0
    assert stats["cv"] is not None


def test_persist_and_publish(db):
    received = []
    event_bus.subscribe(SOCIAL_UPDATED, lambda p: received.append(p))
    res = compute_and_persist(db, "2025", DATASET)
    assert db.query(DevelopmentScore).count() == 3
    assert res["distribution"]["n"] == 3
    assert len(received) == 1
    assert received[0]["period"] == "2025"
    # richer region should out-score the poorest
    assert get_latest(db, "santo_domingo").development_score > get_latest(db, "sur_profundo").development_score


def test_empty_dataset_raises(db):
    with pytest.raises(ValueError):
        compute_and_persist(db, "2025", {})
