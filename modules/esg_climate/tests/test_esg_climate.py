"""Tests for esg_climate: IRC nacional (ND-GAIN panel), persistence, events.

The IRC was re-scoped from per-sector to per-country (Caribbean/LatAm panel).
Physical/adaptive/governance come from real ND-GAIN; transition is declared
rubric until the energy source is wired (Gate C).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from shared.data.ndgain_client import ndgain_client
from modules.esg_climate.events import ESG_UPDATED
from modules.esg_climate.models.models import ESGScore, EnvIndicator  # noqa: F401 — register tables
from modules.esg_climate.scoring.exposure import IRC_CONFIG, compute_irc
from modules.esg_climate.service import (
    IRC_PANEL,
    assemble_irc_dataset,
    compute_and_persist,
    esg_sync,
    get_latest,
)


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


def test_ndgain_fixture_has_the_panel():
    panel = ndgain_client.panel(list(IRC_PANEL))
    assert "DOM" in panel
    assert panel["DOM"]["governance"] > 0          # real value present
    assert ndgain_client.reference_year()           # year stamped


def test_assemble_marks_real_vs_rubric(db):
    asm = assemble_irc_dataset(db)
    assert asm["has_live"] and asm["dataset"].get("DOM")
    src = asm["sources"]["DOM"]
    # ND-GAIN dimensions are live; transition is declared rubric.
    assert src["governance_quality"] == "live"
    assert src["hurricane_exposure"] == "live"
    assert src["fossil_dependence"] == "rubric"
    assert src["carbon_intensity"] == "rubric"


def test_compute_irc_inverts_risk_variables(db):
    asm = assemble_irc_dataset(db)
    res = compute_irc("DOM", asm["dataset"])
    assert 0.0 <= res["esg_score"] <= 100.0
    exp = res["dimensions"]["physical_risk"]["variables"]["hurricane_exposure"]
    assert exp["inverted"] is True                  # higher exposure = worse → inverted


def test_hurricane_exposure_overrides_physical(db):
    # When HURDAT2 exposure is supplied, it feeds hurricane_exposure (still live).
    asm = assemble_irc_dataset(db, hurricane_exp={"DOM": 240.0})
    assert asm["dataset"]["DOM"]["hurricane_exposure"] == 240.0
    assert asm["sources"]["DOM"]["hurricane_exposure"] == "live"


def test_sync_persists_panel_and_publishes(db):
    received = []
    event_bus.subscribe(ESG_UPDATED, lambda p: received.append(p))
    res = esg_sync(db)
    assert res["errors"] == [] and res["scored"] == res["countries"] > 1
    assert db.query(ESGScore).count() == res["scored"]
    assert len(received) == 1 and received[0]["period"] == res["period"]
    dr = get_latest(db, "DOM")
    assert dr is not None and dr.esg_score is not None
    assert dr.entity_key == "DOM"


def test_empty_dataset_raises(db):
    with pytest.raises(ValueError):
        compute_and_persist(db, "2025", {})
