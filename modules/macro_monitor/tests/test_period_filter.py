"""Tests for future-period filtering + chronological period handling (T4B P1)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.macro_monitor.models.models import MacroSeries  # noqa: F401
from modules.macro_monitor.service import (
    _series_by_code, build_snapshot, get_indicators, period_end_date,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _bus():
    event_bus.clear()
    yield
    event_bus.clear()


def _seed(db, code, period, value):
    db.add(MacroSeries(series_code=code, period=period, value=value))


# ── period_end_date ─────────────────────────────────────────────

def test_period_end_date_formats():
    assert period_end_date("2025") == date(2025, 12, 31)
    assert period_end_date("2025-03") == date(2025, 3, 31)   # last day of March
    assert period_end_date("2024-02") == date(2024, 2, 29)   # leap year
    assert period_end_date("2025-Q2") == date(2025, 6, 30)
    assert period_end_date("2025-q4") == date(2025, 12, 31)  # case-insensitive
    assert period_end_date(None) is None
    assert period_end_date("garbage") is None


# ── future filtering ────────────────────────────────────────────

def test_series_by_code_drops_future(db):
    _seed(db, "x", "2020-01", 1.0)
    _seed(db, "x", "2020-02", 2.0)
    _seed(db, "x", "2099-12", 999.0)  # far future → dropped
    db.commit()
    grouped = _series_by_code(db)
    periods = [p for p, _ in grouped["x"]]
    assert "2099-12" not in periods
    assert periods == ["2020-01", "2020-02"]
    # opt-in keeps them
    assert "2099-12" in [p for p, _ in _series_by_code(db, include_future=True)["x"]]


def test_indicators_latest_is_last_non_future(db):
    _seed(db, "x", "2020-01", 1.0)
    _seed(db, "x", "2020-02", 2.0)
    _seed(db, "x", "2099-12", 999.0)
    db.commit()
    ind = {i["series_code"]: i for i in get_indicators(db)}
    assert ind["x"]["latest_period"] == "2020-02"
    assert ind["x"]["latest_value"] == 2.0  # NOT the future 999


def test_snapshot_period_is_latest_closed_not_future(db):
    _seed(db, "x", "2025-Q4", 1.0)
    _seed(db, "x", "2026-05", 2.0)   # latest closed (May 2026 > Q4 2025)
    _seed(db, "x", "2099-01", 9.0)   # future → ignored
    db.commit()
    res = build_snapshot(db)
    assert res["period"] == "2026-05"  # chronological, future excluded


def test_snapshot_period_mixed_formats_chronological(db):
    # Lexical max would pick "2026-Q1" over "2026-06"; chronological must pick June.
    _seed(db, "a", "2026-Q1", 1.0)
    _seed(db, "a", "2026-06", 2.0)
    db.commit()
    res = build_snapshot(db)
    assert res["period"] == "2026-06"
