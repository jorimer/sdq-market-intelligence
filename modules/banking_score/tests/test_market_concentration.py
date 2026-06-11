"""Tests for system-level market concentration (CR5/CR10/HHI of the EIF)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
import shared.auth.models  # noqa: F401 — register users table for FK resolution
from modules.banking_score.models.models import Bank, BankType, BankingData
from modules.banking_score.scoring.market_concentration import compute_market_concentration


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add(db, name, btype, assets, period=date(2025, 12, 31)):
    b = Bank(name=name, bank_type=btype, is_active=True)
    db.add(b)
    db.flush()
    db.add(BankingData(bank_id=b.id, period_end=period, activos_totales=assets))


def test_cr10_cr5_hhi_over_eif_only(db):
    # 12 EIF banks with decreasing assets + a cambiaria/fiduciaria that must be EXCLUDED.
    sizes = [400, 300, 100, 50, 40, 30, 25, 20, 15, 10, 6, 4]  # sum EIF = 1000
    for i, s in enumerate(sizes):
        _add(db, f"Banco {i}", BankType.banca_multiple, s)
    _add(db, "Agente Cambio X", BankType.cambiaria, 999)      # excluded
    _add(db, "Fiduciaria Y", BankType.fiduciaria, 999)        # excluded
    db.commit()

    r = compute_market_concentration(db, metric="activos")
    assert r["available"] is True
    assert r["n_entities"] == 12                      # cambiaria/fiduciaria excluded
    assert r["total"] == 1000
    # CR5 = (400+300+100+50+40)/1000 = 89%; CR10 = first ten = 1000-6-4 = 990 → 99%
    assert r["cr5"] == 89.0
    assert r["cr10"] == 99.0
    assert r["top10"][0]["name"] == "Banco 0"
    assert r["top10"][0]["share"] == 40.0
    assert len(r["top10"]) == 10
    # HHI on ×10000 scale, positive and within bounds
    assert 0 < r["hhi"] <= 10000


def test_unavailable_when_no_data(db):
    r = compute_market_concentration(db, metric="activos")
    assert r["available"] is False


def test_invalid_metric_raises(db):
    with pytest.raises(ValueError):
        compute_market_concentration(db, metric="patrimonio")
