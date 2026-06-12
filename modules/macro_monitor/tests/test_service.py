"""Tests for macro_monitor ingestion, snapshot persistence and events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.macro_monitor.events import MACRO_UPDATED
from modules.macro_monitor.models.models import (  # noqa: F401 — register tables
    MacroSeries,
    MacroSnapshot,
)
from modules.macro_monitor.service import (
    build_snapshot,
    delete_series,
    get_indicators,
    get_snapshot,
    ingest_series,
)


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


def test_ingest_populates_series(db):
    n = ingest_series(db)
    assert n > 0
    # gdp_growth fixture has a null Q2 — preserved, not interpolated
    gdp = db.query(MacroSeries).filter_by(series_code="gdp_growth", period="2025-Q2").one()
    assert gdp.value is None
    assert gdp.source == "BCRD"


def test_build_snapshot_persists_and_publishes(db):
    received = []
    event_bus.subscribe(MACRO_UPDATED, lambda p: received.append(p))

    ingest_series(db)
    result = build_snapshot(db)

    # persisted
    snap = db.query(MacroSnapshot).one()
    assert snap.period == "2025-Q2"
    assert "gdp_growth" in snap.momentum
    # signals: debt elevado (62.4) + sudden stop in remittances (2710 → 2180)
    kinds = {s["signal"] for s in snap.signals}
    assert "debt_overhang" in kinds
    assert "sudden_stop" in kinds

    # published
    assert len(received) == 1
    assert received[0]["period"] == "2025-Q2"
    assert received[0]["signal_count"] == len(snap.signals)
    assert result["snapshot_id"] == snap.id


def test_build_snapshot_idempotent_per_period(db):
    ingest_series(db)
    build_snapshot(db)
    build_snapshot(db)
    assert db.query(MacroSnapshot).count() == 1


def test_build_without_ingest_raises(db):
    with pytest.raises(ValueError):
        build_snapshot(db)


def test_delete_series_removes_only_that_code(db):
    ingest_series(db)
    # seed an orphan code of the old schema alongside the real series
    db.add(MacroSeries(series_code="bcrd.x.cuentas_corrientes.2023", period="2026-06", value=1.0))
    db.commit()
    before = db.query(MacroSeries).filter_by(series_code="gdp_growth").count()

    deleted = delete_series(db, "bcrd.x.cuentas_corrientes.2023")

    assert deleted == 1
    assert db.query(MacroSeries).filter_by(series_code="bcrd.x.cuentas_corrientes.2023").count() == 0
    # untouched series survive
    assert db.query(MacroSeries).filter_by(series_code="gdp_growth").count() == before


def test_delete_series_idempotent_for_absent_code(db):
    ingest_series(db)
    assert delete_series(db, "no.such.code") == 0


def test_get_indicators_and_snapshot(db):
    ingest_series(db)
    build_snapshot(db)

    indicators = get_indicators(db)
    codes = {i["series_code"] for i in indicators}
    assert {"gdp_growth", "inflation_yoy", "remittances", "public_debt_gdp"} <= codes

    # each indicator carries a human label + unit for the UI
    by_code = {i["series_code"]: i for i in indicators}
    assert by_code["gdp_growth"]["label"] == "Crecimiento del PIB"
    assert by_code["gdp_growth"]["unit"] == "%"
    assert all("label" in i and "unit" in i for i in indicators)
    # n_obs lets the UI default the trajectory chart to a series with depth
    assert all("n_obs" in i and i["n_obs"] >= 1 for i in indicators)

    latest = get_snapshot(db)
    assert latest is not None
    assert latest.period == "2025-Q2"
