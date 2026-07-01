"""Tests de la capa de soporte/sistémico + techo soberano (Fase 6). NO muta el standalone."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — FK de BankingData.uploaded_by
from modules.banking_score.models.models import Bank, BankType, BankingData
from modules.banking_score.scoring.support import (
    STATE_OWNED, sovereign_anchor, support_overlay)

_BANRESERVAS = "Banco de Reservas de la República Dominicana"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, Bank.__table__, BankingData.__table__])
    return sessionmaker(bind=engine)()


def _bank(db, name, activos, depositos):
    b = Bank(name=name, bank_type=BankType.banca_multiple, is_active=True)
    db.add(b)
    db.flush()
    db.add(BankingData(bank_id=b.id, period_end=date(2025, 12, 31),
                       activos_totales=activos, depositos_totales=depositos))
    return b


def test_sovereign_anchor_is_declared_datum():
    sov = sovereign_anchor()
    assert sov["rating"] == "BB"
    assert sov["agency"] == "S&P"
    assert sov["score"] == 45          # rating_scale["BB"]
    assert sov["as_of"]                # fecha declarada presente


def test_support_overlay_state_owned_and_systemic():
    # Banreservas como la mayor por activos → estatal + sistémica (top-1, dentro del CR5).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[User.__table__, Bank.__table__, BankingData.__table__])
    s = sessionmaker(bind=engine)()
    br = _bank(s, _BANRESERVAS, 900_000, 700_000)
    for i in range(6):  # 6 pares menores → Banreservas es top-1
        _bank(s, f"Banco {i}", 100_000 - i * 5_000, 80_000)
    s.commit()

    ov = support_overlay(s, br, 86.7, "SDQ-AA", date(2025, 12, 31))
    assert ov["state_owned"] is True
    assert ov["systemic"]["is_systemic"] is True
    assert ov["systemic"]["rank_activos"] == 1
    assert ov["systemic"]["activos_share"] is not None
    assert ov["sovereign"]["rating"] == "BB"
    # el standalone viaja intacto (no se muta)
    assert ov["standalone"] == {"score": 86.7, "tier": "SDQ-AA"}
    # Propensión ALTA (estatal + sistémica) PERO capacidad acotada por soberano especulativo BB.
    txt = ov["support_assessment"]
    assert "Propensión de soporte ALTA" in txt
    assert "ACOTADA" in txt and "INCIERTO" in txt  # capacidad soberana (BB < grado inversión)


def test_support_overlay_not_state_not_systemic(db):
    # Un banco pequeño no estatal, fuera del top: no sistémico, sin soporte extraordinario.
    big = [_bank(db, f"Grande {i}", 900_000 - i * 10_000, 700_000) for i in range(6)]
    small = _bank(db, "Banco Pequeño", 5_000, 3_000)
    db.commit()
    ov = support_overlay(db, small, 60.0, "SDQ-BBB+", date(2025, 12, 31))
    assert ov["state_owned"] is False
    assert ov["systemic"]["is_systemic"] is False
    assert "Sin soporte extraordinario" in ov["support_assessment"]
    assert big  # (usado para poblar el panel)


def test_private_systemic_support_capped_by_speculative_sovereign():
    """Banco Popular (privado, sistémico) en soberano BB: la propensión sistémica se lee
    ACOTADA por la capacidad fiscal del soberano especulativo — no 'soporte plausible' pelado."""
    from modules.banking_score.scoring.support import _support_assessment
    txt = _support_assessment(state_owned=False, is_systemic=True,
                              sovereign={"rating": "BB", "score": 45})
    assert "importancia sistémica" in txt          # pata 1: propensión
    assert "ACOTADA" in txt and "INCIERTO" in txt   # pata 2: capacidad soberana limitada
    assert "grado especulativo" in txt
    # Con un soberano de grado de inversión, la capacidad NO se acota.
    inv = _support_assessment(state_owned=False, is_systemic=True,
                              sovereign={"rating": "A", "score": 75})
    assert "grado de inversión" in inv and "ACOTADA" not in inv


def test_banreservas_in_state_owned_set():
    assert _BANRESERVAS in STATE_OWNED
