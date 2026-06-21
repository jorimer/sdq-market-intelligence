"""Tests del registro de deals (HistoricalDeal) y su seed."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from modules.deal_scoring.models.models import (
    DealStage,
    DealType,
    HistoricalDeal,
    LabelConfidence,
    Sector,
)
from modules.deal_scoring.seed.historical_deals_seed import SEED, load_seed


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_create_and_query_deal(session):
    d = HistoricalDeal(
        deal_name="Test Deal", deal_type=DealType.real_estate, sector=Sector.real_estate,
        country="DO", deal_size_usd=1_000_000, equity_required_pct=25,
        deal_stage=DealStage.term_sheet, closed_successfully=True,
        label_confidence=LabelConfidence.alta,
    )
    session.add(d)
    session.commit()
    got = session.query(HistoricalDeal).filter_by(deal_name="Test Deal").one()
    assert got.country == "DO"
    assert got.closed_successfully is True
    assert got.id is not None and got.created_at is not None


def test_seed_loads(session):
    inserted = load_seed(session)
    assert inserted == len(SEED)
    assert session.query(HistoricalDeal).count() == len(SEED)


def test_seed_idempotent(session):
    load_seed(session)
    again = load_seed(session)  # only_if_empty -> no duplica
    assert again == 0
    assert session.query(HistoricalDeal).count() == len(SEED)


def test_seed_has_both_classes(session):
    """El dataset debe tener positivos Y negativos (requisito del clasificador)."""
    load_seed(session)
    pos = session.query(HistoricalDeal).filter_by(closed_successfully=True).count()
    neg = session.query(HistoricalDeal).filter_by(closed_successfully=False).count()
    assert pos >= 1, "faltan deals cerrados (clase 1)"
    assert neg >= 1, "faltan deals no cerrados (clase 0)"


def test_analyst_scores_nullable(session):
    """La columna acepta NULL y no-NULL: persisten ambos casos."""
    sin = HistoricalDeal(deal_name="Sin scores", deal_type=DealType.venture,
                         sector=Sector.other, country="DO",
                         label_confidence=LabelConfidence.baja)
    con = HistoricalDeal(deal_name="Con scores", deal_type=DealType.venture,
                         sector=Sector.other, country="DO",
                         promoter_track_record=70, financial_quality=65,
                         market_validation=80, regulatory_readiness=55,
                         label_confidence=LabelConfidence.alta)
    session.add_all([sin, con])
    session.commit()
    assert session.query(HistoricalDeal).filter_by(deal_name="Sin scores").one(
        ).promoter_track_record is None
    assert session.query(HistoricalDeal).filter_by(deal_name="Con scores").one(
        ).promoter_track_record == 70
