"""Tests for the entity-level drill-down (overall + drivers + peers)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — register users table for FK
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.scoring.entity_insight import ai_context_entity, build_entity_insight


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _rr(db, bank, period, overall, subs, details=None):
    db.add(RatingResult(
        bank_id=bank.id, period_end=period, overall_score=overall, rating_tier="SDQ-A",
        model_type=ModelType.deterministic,
        solidez_score=subs[0], calidad_score=subs[1], eficiencia_score=subs[2],
        liquidez_score=subs[3], diversificacion_score=subs[4],
        indicator_details=details or {},
    ))


def test_build_entity_insight_drivers_and_peers(db):
    bm1 = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    bm2 = Bank(name="Banco Dos", bank_type=BankType.banca_multiple)
    aap = Bank(name="Asoc Tres", bank_type=BankType.aap)
    db.add_all([bm1, bm2, aap])
    db.flush()
    details = {
        # solidez group: solvencia high (driver), patrimonio_activos low (drag)
        "solvencia": {"raw": 18.0, "score": 100.0, "available": True},
        "patrimonio_activos": {"raw": 8.0, "score": 40.0, "available": True},
        "morosidad": {"raw": 2.0, "score": 80.0, "available": True},
    }
    _rr(db, bm1, date(2025, 9, 30), 70, (80, 75, 60, 65, 0), details)  # history
    _rr(db, bm1, date(2025, 12, 31), 82, (90, 80, 60, 65, 0), details)
    _rr(db, bm2, date(2025, 12, 31), 60, (60, 55, 50, 60, 0))  # peer
    _rr(db, aap, date(2025, 12, 31), 50, (50, 45, 40, 55, 0))  # peer (other type)
    db.commit()

    d = build_entity_insight(db, bm1)
    assert d["latest"]["period_end"] == "2025-12-31"
    assert d["latest"]["overall_score"] == 82.0
    # sub-components present with weights
    solidez = next(s for s in d["sub_components"] if s["key"] == "solidez")
    assert solidez["score"] == 90.0
    assert solidez["weight"] == 0.40
    assert solidez["driver"]["key"] == "solvencia"   # highest score in group
    assert solidez["drag"]["key"] == "patrimonio_activos"  # lowest
    # trend chronological
    assert [t["period_end"] for t in d["trend"]] == ["2025-09-30", "2025-12-31"]
    # peers: sector (3 banks, bm1=82 top) and same type (bm1=82, bm2=60)
    assert d["peers"]["sector"]["n"] == 3
    assert d["peers"]["sector"]["percentile"] == 100.0
    assert d["peers"]["entity_type"]["n"] == 2
    assert d["peers"]["entity_type_label"] == "banca_multiple"


def test_build_entity_insight_no_ratings(db):
    bank = Bank(name="X", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.commit()
    assert build_entity_insight(db, bank) is None


def test_ai_context_entity_shape(db):
    bank = Bank(name="Y", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    _rr(db, bank, date(2025, 12, 31), 75, (80, 70, 60, 65, 50),
        {"solvencia": {"raw": 16.0, "score": 95.0, "available": True}})
    db.commit()
    ctx = ai_context_entity(build_entity_insight(db, bank))
    assert ctx["entidad"] == "Y"
    assert ctx["score_global"] == 75.0
    assert len(ctx["sub_componentes"]) == 5
    assert ctx["sub_componentes"][0]["componente"] == "Solidez financiera"
