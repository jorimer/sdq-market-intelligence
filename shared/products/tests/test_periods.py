"""Tests del helper de períodos disponibles (selector de período del reporte)."""
from datetime import date

from sqlalchemy import Column, Date, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from shared.products.periods import distinct_periods, period_sort_key

_Base = declarative_base()


class _Row(_Base):
    __tablename__ = "_pr_test"
    id = Column(Integer, primary_key=True)
    period = Column(String)
    period_end = Column(Date)
    scope = Column(String)


def test_period_sort_key_orders_mixed_formats():
    periods = ["2024", "2025-Q1", "2025-Q4", "2025", "2025-03", "2025-03-31"]
    ordered = sorted(periods, key=period_sort_key, reverse=True)
    # el año desnudo "2025" va después (más alto) que cualquier sub-período de 2025
    assert ordered[0] == "2025"
    assert ordered.index("2025-Q4") < ordered.index("2025-Q1")
    assert ordered[-1] == "2024"


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    _Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_distinct_periods_string_newest_first():
    db = _db()
    for p in ["2023", "2025", "2024", "2025"]:  # con duplicado
        db.add(_Row(period=p, scope="a"))
    db.commit()
    assert distinct_periods(db, _Row.period) == ["2025", "2024", "2023"]


def test_distinct_periods_dates_to_iso():
    db = _db()
    db.add(_Row(period_end=date(2025, 12, 31)))
    db.add(_Row(period_end=date(2025, 6, 30)))
    db.commit()
    assert distinct_periods(db, _Row.period_end) == ["2025-12-31", "2025-06-30"]


def test_distinct_periods_filtered():
    db = _db()
    db.add(_Row(period="2025", scope="a"))
    db.add(_Row(period="2024", scope="b"))
    db.commit()
    assert distinct_periods(db, _Row.period, where=_Row.scope == "a") == ["2025"]


def test_distinct_periods_defensive_on_error():
    # Una sesión inutilizable (sin tabla) → [] en vez de propagar (nunca rompe el producto).
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db = sessionmaker(bind=eng)()  # _pr_test NO creada en este engine
    assert distinct_periods(db, _Row.period) == []
