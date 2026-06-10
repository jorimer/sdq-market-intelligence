"""Tests for the per-indicator drill-down (detail + trend + peer stats)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — register users table for FK at create_all
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.scoring.indicator_detail import (
    INDICATOR_META,
    _band,
    _peer_stats,
    ai_context,
    build_indicator_detail,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _rating(db, bank, period, morosidad_score, raw, available=True):
    db.add(RatingResult(
        bank_id=bank.id, period_end=period, overall_score=70, rating_tier="SDQ-A",
        model_type=ModelType.deterministic,
        indicator_details={"morosidad": {"raw": raw, "score": morosidad_score, "available": available}},
    ))


# ── pure helpers ──

def test_band_thresholds():
    assert _band(90) == "fuerte"
    assert _band(75) == "adecuado"
    assert _band(60) == "moderado"
    assert _band(40) == "débil"


def test_peer_stats_percentile():
    stats = _peer_stats([10.0, 50.0, 90.0], 50.0)
    assert stats["n"] == 3
    assert stats["median_score"] == 50.0
    assert stats["percentile"] == pytest.approx(66.7, abs=0.2)  # 2 of 3 at/below


def test_peer_stats_empty():
    assert _peer_stats([], 50.0) is None


# ── full drill-down ──

def test_build_indicator_detail_trend_and_peers(db):
    bm1 = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    bm2 = Bank(name="Banco Dos", bank_type=BankType.banca_multiple)
    aap = Bank(name="Asoc Tres", bank_type=BankType.aap)
    db.add_all([bm1, bm2, aap])
    db.flush()
    # two periods of history for bm1 (trend)
    _rating(db, bm1, date(2025, 9, 30), morosidad_score=70, raw=3.0)
    _rating(db, bm1, date(2025, 12, 31), morosidad_score=80, raw=2.0)
    # peers at the latest period
    _rating(db, bm2, date(2025, 12, 31), morosidad_score=40, raw=6.0)
    _rating(db, aap, date(2025, 12, 31), morosidad_score=60, raw=4.0)
    db.commit()

    detail = build_indicator_detail(db, bm1, "morosidad")
    assert detail["label"] == INDICATOR_META["morosidad"]["label"]
    assert detail["sub_component"] == "calidad"
    # latest = the most recent period
    assert detail["latest"]["period_end"] == "2025-12-31"
    assert detail["latest"]["score"] == 80.0
    assert detail["latest"]["band"] == "adecuado"
    # trend chronological, only available periods
    assert [t["period_end"] for t in detail["trend"]] == ["2025-09-30", "2025-12-31"]
    # sector peers = all 3 banks at 2025-12 (scores 80/40/60); bm1=80 → top → 100th pct
    assert detail["peers"]["sector"]["n"] == 3
    assert detail["peers"]["sector"]["percentile"] == 100.0
    # entity-type peers = only banca_multiple (bm1=80, bm2=40) → n=2
    assert detail["peers"]["entity_type"]["n"] == 2
    assert detail["peers"]["entity_type_label"] == "banca_multiple"


def test_build_indicator_detail_unknown_key(db):
    bank = Bank(name="X", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.commit()
    assert build_indicator_detail(db, bank, "no_existe") is None


def test_build_indicator_detail_no_ratings(db):
    bank = Bank(name="Y", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.commit()
    assert build_indicator_detail(db, bank, "morosidad") is None


def test_na_indicator_marked_unavailable(db):
    bank = Bank(name="Z", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    _rating(db, bank, date(2025, 12, 31), morosidad_score=0, raw=None, available=False)
    db.commit()
    detail = build_indicator_detail(db, bank, "morosidad")
    assert detail["latest"]["available"] is False
    assert detail["peers"] is None  # no peer comparison when N/D
    assert detail["trend"] == []  # unavailable periods excluded from trend


def test_ai_context_bounds_trend(db):
    bank = Bank(name="W", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    qday = {3: 31, 6: 30, 9: 30, 12: 31}
    for i in range(16):  # 16 quarters → ai_context keeps last 12
        m = (i % 4) * 3 + 3
        _rating(db, bank, date(2021 + i // 4, m, qday[m]), morosidad_score=70, raw=3.0)
    db.commit()
    detail = build_indicator_detail(db, bank, "morosidad")
    ctx = ai_context(detail)
    assert len(ctx["tendencia"]) == 12
    assert ctx["indicador"] == INDICATOR_META["morosidad"]["label"]
