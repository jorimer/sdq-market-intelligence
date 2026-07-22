"""Tests de la superficie de Data API del IRMP (score de panel por país)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_political_risk.models.models import (
    Country,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
)
from modules.macro_political_risk.service import (
    describe_irmp_for_api,
    irmp_observations_for_api,
)
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        Country.__table__, IRMPSnapshot.__table__, DimensionScore.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _snap(db, iso, name, day, score, band=RiskBand.moderado, with_dims=True):
    c = db.query(Country).filter_by(iso_code=iso).one_or_none()
    if c is None:
        c = Country(iso_code=iso, name=name, is_active=True)
        db.add(c)
        db.flush()
    snap = IRMPSnapshot(country_id=c.id, period_end=day, irmp_score=score,
                        risk_band=band, model_version="1.0")
    db.add(snap)
    db.flush()
    if with_dims:
        db.add(DimensionScore(snapshot_id=snap.id, dimension="macro",
                              score=70.0, weight=0.3, contribution=21.0))
    db.commit()
    return snap


def test_descriptor_reflects_the_panel(db):
    _snap(db, "DOM", "República Dominicana", date(2026, 6, 30), 61.2)
    _snap(db, "PER", "Perú", date(2026, 6, 30), 55.4)
    d = describe_irmp_for_api(db)
    assert d["code"] == "irmp" and d["subject_kind"] == "country"
    assert set(d["subjects"]) == {"DOM", "PER"} and d["n_obs"] == 2
    assert d["direction"].startswith("mayor score")
    assert d["period_latest"] == "2026-06-30"


def test_panel_view_returns_latest_per_country(db):
    _snap(db, "DOM", "RD", date(2026, 3, 31), 58.0)
    _snap(db, "DOM", "RD", date(2026, 6, 30), 61.2)
    _snap(db, "PER", "Perú", date(2026, 6, 30), 55.4)
    out = irmp_observations_for_api(db)
    by = {o["subject"]: o for o in out}
    assert len(out) == 2 and by["DOM"]["score"] == 61.2      # el viejo no aparece


def test_subject_view_returns_the_trajectory_with_dimensions(db):
    _snap(db, "DOM", "RD", date(2026, 3, 31), 58.0)
    _snap(db, "DOM", "RD", date(2026, 6, 30), 61.2)
    out = irmp_observations_for_api(db, subject="dom")        # case-insensitive
    assert [o["period"] for o in out] == ["2026-06-30", "2026-03-31"]
    assert out[0]["dimensions"]["macro"]["contribution"] == 21.0
    assert out[0]["band"] == "Moderado"   # el valor visible del enum, no la clave


def test_date_range_filters(db):
    _snap(db, "DOM", "RD", date(2025, 12, 31), 57.0)
    _snap(db, "DOM", "RD", date(2026, 6, 30), 61.2)
    out = irmp_observations_for_api(db, subject="DOM", start="2026-01-01")
    assert [o["period"] for o in out] == ["2026-06-30"]


def test_snapshot_without_dimensions_serves_none_not_empty_lie(db):
    _snap(db, "DOM", "RD", date(2026, 6, 30), 61.2, with_dims=False)
    out = irmp_observations_for_api(db, subject="DOM")
    assert out[0]["dimensions"] is None
