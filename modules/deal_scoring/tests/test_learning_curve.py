"""Tests del learning-curve (graduación rúbrica→modelo) — el núcleo anti-fabricación."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.database.base import Base
from modules.deal_scoring.models.models import (
    DealStage, DealType, HistoricalDeal, LabelConfidence, Sector,
)
from modules.deal_scoring.validation.learning_curve import MIN_LABELED, build_report


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _deal(name, closed, stage="legal", size=1_000_000, retrospective=False):
    return HistoricalDeal(
        deal_name=name, deal_type=DealType.advisory, sector=Sector.other, country="DO",
        deal_stage=DealStage(stage), deal_size_usd=size,
        closed_successfully=closed, label_confidence=LabelConfidence.media,
        retrospective=retrospective,
    )


def test_insufficient_labels_stays_rubrica(session):
    """Pocos labels → NO computa AUC; sigue en rúbrica (honesto)."""
    for i in range(5):
        session.add(_deal(f"c{i}", True))
        session.add(_deal(f"l{i}", False))
    session.commit()
    r = build_report(session)
    assert r["computed"] is False
    assert r["status"] == "rubrica"
    assert r["ready_for_model"] is False
    assert r["n_labeled"] == 10  # < MIN_LABELED


def test_open_deals_excluded_from_labels(session):
    """Deals abiertos (closed=None) no cuentan como labels."""
    for i in range(MIN_LABELED):
        session.add(_deal(f"o{i}", None))
    session.commit()
    r = build_report(session)
    assert r["n_labeled"] == 0
    assert r["ready_for_model"] is False


def test_ready_for_model_only_when_ci_clears_floor(session):
    """Con suficientes labels balanceados se computa el AUC; pero ready_for_model es
    VERDADERO solo si el IC inferior supera el umbral — nunca se fuerza (anti-fabricación)."""
    for i in range(15):
        session.add(_deal(f"c{i}", True, stage="legal", size=5_000_000))
        session.add(_deal(f"l{i}", False, stage="initial", size=100_000))
    session.commit()
    r = build_report(session)
    assert r["computed"] is True
    assert r["n_closed"] == 15 and r["n_lost"] == 15
    assert r["n_ex_ante"] == 30  # por defecto los deals son ex-ante
    assert r["cv_auc"] is not None and r["auc_ci"][0] is not None
    # El gate de graduación se deriva exactamente del IC inferior > umbral.
    assert r["ready_for_model"] == (r["auc_ci"][0] > r["graduation_floor"])


def test_retrospective_labels_never_graduate(session):
    """Labels retrospectivos (backfill, con el outcome conocido) NO gradúan el modelo
    aunque su AUC in-sample sea altísimo — núcleo anti-fuga."""
    # 30 retrospectivos perfectamente separables (cerró=legal+grande, perdió=initial+chico).
    for i in range(15):
        session.add(_deal(f"c{i}", True, stage="legal", size=5_000_000, retrospective=True))
        session.add(_deal(f"l{i}", False, stage="initial", size=100_000, retrospective=True))
    session.commit()
    r = build_report(session)
    # Sin labels ex-ante → sigue en rúbrica, no computa graduación.
    assert r["status"] == "rubrica"
    assert r["ready_for_model"] is False
    assert r["computed"] is False
    assert r["n_labeled"] == 30 and r["n_ex_ante"] == 0 and r["n_retrospective"] == 30
    # Pero SÍ se reporta el diagnóstico in-sample, marcado como sujeto a fuga.
    diag = r["retrospective_diagnostic"]
    assert diag is not None and diag["n"] == 30
    assert diag["cv_auc"] is not None
    assert "fuga" in diag["note"].lower()


def test_ex_ante_graduate_while_retrospective_ignored(session):
    """Mezcla: los ex-ante deciden la graduación; los retrospectivos no la afectan."""
    for i in range(15):
        session.add(_deal(f"xc{i}", True, stage="legal", size=5_000_000))   # ex-ante
        session.add(_deal(f"xl{i}", False, stage="initial", size=100_000))  # ex-ante
    for i in range(10):  # ruido retrospectivo que NO debe contar para graduar
        session.add(_deal(f"rc{i}", True, retrospective=True))
        session.add(_deal(f"rl{i}", False, retrospective=True))
    session.commit()
    r = build_report(session)
    assert r["computed"] is True
    assert r["n_ex_ante"] == 30 and r["n_retrospective"] == 20
    assert r["n_labeled"] == 50
    # La graduación se computa SOLO sobre los 30 ex-ante.
    assert r["ready_for_model"] == (r["auc_ci"][0] > r["graduation_floor"])
