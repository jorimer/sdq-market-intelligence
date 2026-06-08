"""Tests for the SIB backfill/sync service (no network — stubbed client)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.banking_score import sib_sync
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    BankType,
    DataSource,
    RatingResult,
)


@pytest.fixture()
def Session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    # Make the service use this engine.
    monkeypatch.setattr(sib_sync, "SessionLocal", SessionLocal)
    return SessionLocal


def _seed_popular(db):
    """One real bank (matches SIB short 'Popular') with synthetic data."""
    bank = Bank(name="Banco Popular Dominicano", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    db.add(BankingData(
        bank_id=bank.id, period_end=date(2024, 12, 31),
        source=DataSource.manual, activos_totales=100,
    ))
    db.commit()
    return bank


class _StubClient:
    def __init__(self):
        self.use_proxy = False

    def check_connectivity(self):
        return {"reachable": True, "status_code": 200}

    def get_working_tipos(self):
        return ["BM"]

    def extract_one_tipo(self, tipo, period_start="2021-01"):
        return self.extract_all_entities_bulk(period_start=period_start)

    def extract_all_entities_bulk(self, period_start="2021-01"):
        return {
            "Popular": [
                {"period_end": date(2024, 12, 31), "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 999.0, "patrimonio_tecnico": 50.0},
                # Non-quarter-end → must be skipped.
                {"period_end": date(2024, 11, 30), "period_type": "monthly",
                 "source": "sib_api", "activos_totales": 5.0},
            ],
            "_unmatched": [],
            "_entity_names": [],
        }


def test_needs_backfill(Session):
    db = Session()
    _seed_popular(db)
    assert sib_sync.needs_backfill(db) is True


def test_stats(Session):
    db = Session()
    _seed_popular(db)
    s = sib_sync.bank_data_stats(db)
    assert s["entities"] == 1
    assert s["records"] == 1
    assert s["sib_records"] == 0
    assert s["period_end"] == "2024-12-31"


def test_backfill_replaces_with_real_data(Session, monkeypatch):
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["entities_matched"] == 1
    assert result["periods_skipped_non_quarterly"] == 1  # the Nov row

    db2 = Session()
    row = db2.query(BankingData).filter_by(period_end=date(2024, 12, 31)).first()
    assert row.source == DataSource.sib_api
    assert float(row.activos_totales) == 999.0  # overwritten with real value
    bank = db2.query(Bank).filter_by(name="Banco Popular Dominicano").first()
    assert bank.sib_code == "BPD"  # populated from the SIB catalog


def test_backfill_auto_registers_catalogued_entity(Session, monkeypatch):
    """A SIB entity in the catalog but not in the DB is auto-created."""
    db = Session()
    other = Bank(name="Otro Banco", bank_type=BankType.banca_multiple)
    db.add(other)
    db.flush()
    db.add(BankingData(bank_id=other.id, period_end=date(2024, 12, 31), source=DataSource.manual))
    db.commit()
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["entities_created"] >= 1  # Popular wasn't in the DB → created

    db2 = Session()
    popular = db2.query(Bank).filter_by(name="Banco Popular Dominicano").first()
    assert popular is not None
    assert popular.sib_code == "BPD"
    assert popular.bank_type == BankType.banca_multiple


def test_backfill_recalculates_ratings(Session, monkeypatch):
    """After ingesting SIB data, the backfill must compute and persist ratings
    (closes the gap where data landed but ratings stayed empty/stale)."""
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())

    assert db.query(RatingResult).count() == 0  # no ratings before
    result = sib_sync.run_backfill(force=True)

    assert result["status"] == "completed"
    assert result["periods_scored"] == 1  # the 2024-12-31 quarter-end
    assert result["ratings_written"] == 1
    assert result["ratings_total"] == 1

    db2 = Session()
    rr = db2.query(RatingResult).filter_by(period_end=date(2024, 12, 31)).first()
    assert rr is not None
    assert 0 <= float(rr.overall_score) <= 100
    assert rr.rating_tier


class _FutureQuarterClient(_StubClient):
    """SIB returns a closed quarter plus the in-progress (future) one."""

    def extract_all_entities_bulk(self, period_start="2021-01"):
        from datetime import timedelta
        future = date.today() + timedelta(days=200)
        # Normalize to a quarter-end month so it isn't skipped as non-quarterly.
        fq = date(future.year, ((future.month - 1) // 3) * 3 + 3, 1)
        # Move to a real quarter-end day (30/31) safely beyond today.
        fq = date(fq.year + (1 if fq <= date.today() else 0), 12, 31)
        return {
            "Popular": [
                {"period_end": date(2024, 12, 31), "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 999.0, "patrimonio_tecnico": 50.0},
                {"period_end": fq, "period_type": "quarterly",
                 "source": "sib_api", "activos_totales": 1.0},
            ],
            "_unmatched": [], "_entity_names": [],
        }


def test_backfill_skips_future_quarter(Session, monkeypatch):
    """The in-progress/future quarter must not be ingested or scored."""
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _FutureQuarterClient())

    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "completed"
    assert result["periods_skipped_future"] >= 1

    db2 = Session()
    # No banking_data nor ratings for any future-dated period.
    fut = db2.query(BankingData).filter(BankingData.period_end > date.today()).count()
    fut_r = db2.query(RatingResult).filter(RatingResult.period_end > date.today()).count()
    assert fut == 0
    assert fut_r == 0


def test_prune_future_periods(Session):
    """prune_future_periods removes only future-dated rows."""
    from datetime import timedelta
    db = Session()
    bank = _seed_popular(db)
    future = date.today() + timedelta(days=120)
    db.add(BankingData(bank_id=bank.id, period_end=future, source=DataSource.sib_api))
    db.commit()
    assert db.query(BankingData).filter(BankingData.period_end > date.today()).count() == 1

    res = sib_sync.prune_future_periods(db)
    assert res["data_deleted"] == 1
    assert db.query(BankingData).filter(BankingData.period_end > date.today()).count() == 0
    # The closed-period row survives.
    assert db.query(BankingData).filter_by(period_end=date(2024, 12, 31)).count() == 1


def test_backfill_skipped_when_already_real(Session, monkeypatch):
    db = Session()
    bank = _seed_popular(db)
    # Mark existing data as already-SIB.
    db.query(BankingData).update({BankingData.source: DataSource.sib_api})
    db.commit()
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: _StubClient())
    result = sib_sync.run_backfill(force=False)
    assert result["status"] == "skipped"


def test_backfill_errors_without_key(Session, monkeypatch):
    db = Session()
    _seed_popular(db)
    monkeypatch.setattr(sib_sync, "get_sib_data_client", lambda force_new=False: None)
    result = sib_sync.run_backfill(force=True)
    assert result["status"] == "error"
    assert "clave" in result["message"].lower() or "configur" in result["message"].lower()
