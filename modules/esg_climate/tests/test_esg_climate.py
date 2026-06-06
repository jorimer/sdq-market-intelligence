"""Tests for esg_climate: exposure, materiality, persistence, events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.esg_climate.events import ESG_UPDATED
from modules.esg_climate.models.models import (  # noqa: F401 — register tables
    ESGScore,
    EnvIndicator,
)
from modules.esg_climate.scoring.exposure import IRC_CONFIG, compute_exposure
from modules.esg_climate.service import compute_and_persist, get_latest

DATASET = {
    "turismo": {"hurricane_exposure": 80, "coastal_exposure": 90, "carbon_intensity": 40,
                "fossil_dependence": 55, "adaptation_investment": 45, "diversification": 50,
                "disclosure_quality": 40, "emissions_targets": 35},
    "energia": {"hurricane_exposure": 50, "coastal_exposure": 40, "carbon_intensity": 85,
                "fossil_dependence": 80, "adaptation_investment": 55, "diversification": 45,
                "disclosure_quality": 60, "emissions_targets": 55},
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
    assert round(sum(IRC_CONFIG.dimension_weights.values()), 6) == 1.0


def test_exposure_inverts_risk_variables():
    res = compute_exposure("energia", DATASET)
    assert 0.0 <= res["esg_score"] <= 100.0
    ci = res["dimensions"]["transition_risk"]["variables"]["carbon_intensity"]
    assert ci["inverted"] is True  # higher carbon = worse → inverted

    # energia has higher carbon intensity than turismo → worse transition score
    res_t = compute_exposure("turismo", DATASET)
    assert res["dimensions"]["transition_risk"]["score"] < res_t["dimensions"]["transition_risk"]["score"]


def test_materiality_flag_present():
    res = compute_exposure("turismo", DATASET)
    assert "materiality" in res
    assert res["materiality"]["level"] in {"alta", "media", "baja"}


def test_persist_and_publish(db):
    received = []
    event_bus.subscribe(ESG_UPDATED, lambda p: received.append(p))
    compute_and_persist(db, "2025", DATASET)
    assert db.query(ESGScore).count() == 2
    assert len(received) == 1
    assert received[0]["period"] == "2025"
    row = get_latest(db, "turismo")
    assert row.esg_score is not None
    assert row.materiality_level in {"alta", "media", "baja"}


def test_empty_dataset_raises(db):
    with pytest.raises(ValueError):
        compute_and_persist(db, "2025", {})
