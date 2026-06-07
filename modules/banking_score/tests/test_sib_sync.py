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
