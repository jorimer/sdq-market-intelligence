"""Tests de la superficie de Data API del IRC (score de panel por país)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.esg_climate.models.models import ESGScore
from modules.esg_climate.service import describe_irc_for_api, irc_observations_for_api
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ESGScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _score(db, iso, period, value, dims=None):
    db.add(ESGScore(entity_key=iso, period=period, esg_score=value, band="Moderada",
                    model_version="1.0",
                    breakdown={"dimensions": dims} if dims else None))
    db.commit()


def test_descriptor_and_panel(db):
    _score(db, "DOM", "2025", 55.0, dims={"physical_risk": {"score": 60.0}})
    _score(db, "JAM", "2025", 48.0)
    d = describe_irc_for_api(db)
    assert d["code"] == "irc" and d["subject_kind"] == "country"
    assert d["n_obs"] == 2 and "resiliencia" in d["direction"]

    out = irc_observations_for_api(db)
    by = {o["subject"]: o for o in out}
    assert by["DOM"]["score"] == 55.0
    assert by["DOM"]["dimensions"]["physical_risk"]["score"] == 60.0
    assert by["JAM"]["dimensions"] is None


def test_trajectory_and_null_score_reason(db):
    _score(db, "DOM", "2024", 52.0)
    _score(db, "DOM", "2025", None)
    out = irc_observations_for_api(db, subject="dom")
    assert [o["period"] for o in out] == ["2025", "2024"]
    assert out[0]["score"] is None and out[0]["reason"]
