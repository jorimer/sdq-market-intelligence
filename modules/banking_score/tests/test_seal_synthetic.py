"""Tests for sealing the synthetic banking seed (no fixture financials).

Covers: the catalog-only seed (no BankingData), scoring that ignores
``source=manual``, the per-source stats breakdown, and the synthetic purge with
orphan rating/action cleanup. Offline.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — register users table for FKs
from shared.database.base import Base
from modules.banking_score.models.models import (
    ActionType,
    Bank,
    BankingData,
    BankType,
    DataSource,
    RatingAction,
    RatingResult,
)
from modules.banking_score.scoring.batch import score_all_periods, score_period
from modules.banking_score.sib_sync import bank_data_stats, purge_synthetic_data


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _bank(db, name, t=BankType.banca_multiple):
    b = Bank(name=name, bank_type=t)
    db.add(b)
    db.flush()
    return b


def _data(db, bank, period, source, **kw):
    db.add(BankingData(bank_id=bank.id, period_end=period, source=source,
                       activos_totales=kw.get("activos_totales", 100.0)))


def _rating(db, bank, period):
    db.add(RatingResult(bank_id=bank.id, period_end=period, overall_score=70.0, rating_tier="SDQ-A"))


# ── Catalog-only seed ─────────────────────────────────────────────

def test_seed_banks_creates_catalog_without_financials(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr("shared.database.session.SessionLocal", TestSession)

    from modules.banking_score.seed.banking_seed import BANKING_ENTITIES, seed_banks
    res = seed_banks(verbose=False)

    check = TestSession()
    try:
        assert res["entities_created"] == len(BANKING_ENTITIES)
        assert res["records_created"] == 0
        assert check.query(Bank).count() == len(BANKING_ENTITIES)
        assert check.query(BankingData).count() == 0        # never seeds financials
        # Idempotent: a second run creates nothing.
        res2 = seed_banks(verbose=False)
        assert res2["entities_created"] == 0
        assert res2["entities_existing"] == len(BANKING_ENTITIES)
        assert check.query(BankingData).count() == 0
    finally:
        check.close()


# ── Scoring ignores synthetic data ────────────────────────────────

def test_score_period_excludes_manual(db):
    real = _bank(db, "Real Bank")
    synth = _bank(db, "Synthetic Bank")
    p = date(2024, 12, 31)
    _data(db, real, p, DataSource.sib_api)
    _data(db, synth, p, DataSource.manual)
    db.commit()

    res = score_period(db, p)
    touched = {r["bank_id"] for r in res["results"]} | {e["bank_id"] for e in res["errors"]}
    assert synth.id not in touched          # manual never enters scoring (no rating, no error)
    assert db.query(RatingResult).filter_by(bank_id=synth.id).count() == 0


def test_score_all_periods_skips_manual_only_keeps_real_sources(db):
    real, synth, cambi = _bank(db, "Real"), _bank(db, "Synth"), _bank(db, "Cambiaria")
    _data(db, real, date(2024, 12, 31), DataSource.sib_api)     # real period
    _data(db, synth, date(2023, 12, 31), DataSource.manual)     # manual-only period
    _data(db, cambi, date(2022, 12, 31), DataSource.sib_simbad)  # SIMBAD real period
    db.commit()

    res = score_all_periods(db, only_sib=True)
    scored = {p["period_end"] for p in res["per_period"]}
    assert "2024-12-31" in scored                # sib_api
    assert "2022-12-31" in scored                # SIMBAD preserved
    assert "2023-12-31" not in scored            # purely synthetic → skipped


# ── Per-source visibility ─────────────────────────────────────────

def test_bank_data_stats_by_source(db):
    a, b, c = _bank(db, "A"), _bank(db, "B"), _bank(db, "C")
    _data(db, a, date(2024, 12, 31), DataSource.sib_api)
    _data(db, b, date(2024, 12, 31), DataSource.sib_simbad)
    _data(db, c, date(2024, 12, 31), DataSource.manual)
    db.commit()

    stats = bank_data_stats(db)
    assert stats["by_source"] == {"sib_api": 1, "sib_simbad": 1, "manual": 1}
    assert stats["sib_records"] == 1
    assert stats["synthetic_records"] == 1


# ── Purge synthetic + orphan cleanup ──────────────────────────────

def test_purge_synthetic_removes_manual_and_orphans_keeps_real(db):
    real = _bank(db, "Real")
    synth = _bank(db, "Synth")
    cambi = _bank(db, "Cambiaria")
    p_real, p_synth, p_simbad = date(2024, 12, 31), date(2023, 12, 31), date(2022, 12, 31)

    _data(db, real, p_real, DataSource.sib_api)
    _data(db, cambi, p_simbad, DataSource.sib_simbad)
    _data(db, synth, p_synth, DataSource.manual)
    _rating(db, real, p_real)        # backed by sib_api → keep
    _rating(db, cambi, p_simbad)     # backed by SIMBAD → keep
    _rating(db, synth, p_synth)      # orphaned once manual is purged → delete
    db.add(RatingAction(bank_id=synth.id, period_end=p_synth, action_type=ActionType.confirmacion,
                        new_score=70.0, new_tier="SDQ-A"))   # orphan action → delete
    db.commit()

    res = purge_synthetic_data(db)
    assert res["synthetic_deleted"] == 1
    assert res["orphan_ratings_deleted"] == 1
    assert res["orphan_actions_deleted"] == 1

    assert db.query(BankingData).filter_by(source=DataSource.manual).count() == 0
    assert db.query(BankingData).count() == 2                 # sib_api + simbad survive
    surviving = {r.bank_id for r in db.query(RatingResult).all()}
    assert surviving == {real.id, cambi.id}                   # only real-backed ratings remain
    assert db.query(RatingAction).count() == 0
