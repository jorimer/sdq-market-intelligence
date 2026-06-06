"""Tests for IRMP persistence + event publication (Fase 1B)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.macro_political_risk.events import IRMP_UPDATED
from modules.macro_political_risk.models.models import (  # noqa: F401 — register tables
    Country,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
)
from modules.macro_political_risk.service import (
    compute_and_persist,
    get_history,
    get_latest,
)

DATASET = {
    "DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0,
           "fx_volatility": 3.0, "news_sentiment": 20.0, "discretion": 30.0},
    "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0,
           "fx_volatility": 5.0, "news_sentiment": 10.0, "discretion": 40.0},
    "PA": {"gdp_cagr_3y": 1.0, "public_debt_gdp": 52.0, "wgi_rule_of_law": 50.0,
           "fx_volatility": 8.0, "news_sentiment": -10.0, "discretion": 60.0},
}


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


def test_persists_snapshot_and_dimensions(db):
    res = compute_and_persist(db, "DO", DATASET, date(2025, 12, 31),
                              country_name="República Dominicana", region="Caribe")
    assert "snapshot_id" in res
    snap = db.query(IRMPSnapshot).one()
    assert snap.irmp_score == res["irmp_score"]
    assert isinstance(snap.risk_band, RiskBand)
    # 5 dimension rows persisted
    assert db.query(DimensionScore).count() == 5
    # country upserted with real name
    country = db.query(Country).filter_by(iso_code="DO").one()
    assert country.name == "República Dominicana"


def test_publishes_irmp_updated(db):
    received = []
    event_bus.subscribe(IRMP_UPDATED, lambda p: received.append(p))

    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))

    assert len(received) == 1
    assert received[0]["country_code"] == "DO"
    assert received[0]["risk_band"] in {"Bajo", "Moderado", "Elevado", "Alto"}
    assert "snapshot_id" in received[0]


def test_rerun_is_idempotent_per_period(db):
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))
    # Same country + period → one snapshot, 5 dimension rows (not 10)
    assert db.query(IRMPSnapshot).count() == 1
    assert db.query(DimensionScore).count() == 5


def test_latest_and_history(db):
    compute_and_persist(db, "DO", DATASET, date(2024, 12, 31))
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))

    latest = get_latest(db, "DO")
    assert str(latest.period_end) == "2025-12-31"

    history = get_history(db, "DO")
    assert len(history) == 2
    assert str(history[0].period_end) == "2025-12-31"  # most recent first


def test_unknown_country_raises_and_persists_nothing(db):
    with pytest.raises(KeyError):
        compute_and_persist(db, "XX", DATASET, date(2025, 12, 31))
    assert db.query(IRMPSnapshot).count() == 0
