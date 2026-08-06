"""Tests de amplitud (Fase 4): trayectoria multi-período + percentil vs el sistema."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — register users table for FK
from modules.banking_score.models.models import Bank, BankType, ModelType, RatingResult
from modules.banking_score.scoring.amplitude import entity_trajectories, period_percentiles


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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


def test_entity_trajectories_chronological_and_indicators(db):
    bank = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    _rr(db, bank, date(2025, 6, 30), 70, (80, 70, 60, 65, 50),
        {"solvencia": {"raw": 15.0, "score": 85.0, "available": True}})
    _rr(db, bank, date(2025, 9, 30), 74, (82, 72, 62, 66, 52),
        {"solvencia": {"raw": 15.8, "score": 88.0, "available": True}})
    _rr(db, bank, date(2025, 12, 31), 78, (86, 75, 64, 68, 55),
        {"solvencia": {"raw": 16.8, "score": 92.0, "available": True},
         # N/D en el último período → no debe aparecer en la serie del indicador
         "morosidad": {"raw": None, "score": None, "available": False}})
    db.commit()

    t = entity_trajectories(db, bank)
    assert t["n_periods"] == 3
    assert [p["period_end"] for p in t["overall"]] == ["2025-06-30", "2025-09-30", "2025-12-31"]
    assert t["overall"][-1]["score"] == 78.0
    # sub-componentes cronológicos
    assert [p["score"] for p in t["sub"]["solidez"]] == [80.0, 82.0, 86.0]
    # indicador con serie completa; morosidad N/D no entra
    assert [p["score"] for p in t["indicators"]["solvencia"]] == [85.0, 88.0, 92.0]
    assert "morosidad" not in t["indicators"]


def test_entity_trajectories_window_n(db):
    bank = Bank(name="Banco Largo", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    for i, m in enumerate([3, 6, 9, 12, 3, 6, 9, 12, 3, 6]):
        y = 2023 + (i // 4)
        _rr(db, bank, date(y, m, 28), 60 + i, (60, 60, 60, 60, 60))
    db.commit()

    t = entity_trajectories(db, bank, n=4)
    assert t["n_periods"] == 4
    assert len(t["overall"]) == 4
    # se queda con los 4 más recientes (scores 66..69)
    assert [p["score"] for p in t["overall"]] == [66.0, 67.0, 68.0, 69.0]


def test_entity_trajectories_no_ratings(db):
    bank = Bank(name="Vacío", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.commit()
    t = entity_trajectories(db, bank)
    assert t == {"n_periods": 0, "overall": [], "sub": {}, "indicators": {}}


def test_period_percentiles_sector_and_type(db):
    bm1 = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    bm2 = Bank(name="Banco Dos", bank_type=BankType.banca_multiple)
    aap = Bank(name="Asoc Tres", bank_type=BankType.aap)
    db.add_all([bm1, bm2, aap])
    db.flush()
    p = date(2025, 12, 31)
    _rr(db, bm1, p, 82, (90, 80, 60, 65, 40),
        {"solvencia": {"raw": 18.0, "score": 100.0, "available": True}})
    _rr(db, bm2, p, 60, (60, 55, 50, 60, 40),
        {"solvencia": {"raw": 12.0, "score": 60.0, "available": True}})
    _rr(db, aap, p, 50, (50, 45, 40, 55, 40),
        {"solvencia": {"raw": 10.0, "score": 40.0, "available": True}})
    db.commit()

    pct = period_percentiles(db, bm1, p)
    assert pct["entity_type_label"] == "banca_multiple"
    # overall: bm1=82 es el tope de las 3 → percentil 100 en sector
    assert pct["overall"]["sector"]["n"] == 3
    assert pct["overall"]["sector"]["percentile"] == 100.0
    # entity_type: 2 banca_multiple, bm1 arriba
    assert pct["overall"]["entity_type"]["n"] == 2
    assert pct["overall"]["entity_type"]["percentile"] == 100.0
    # indicador solvencia: bm1=100 tope del sector
    assert pct["indicators"]["solvencia"]["sector"]["percentile"] == 100.0
    # sub-componente diversificacion: las 3 empatan en 40 → percentil 100 (todas <=)
    assert pct["sub"]["diversificacion"]["sector"]["percentile"] == 100.0


def test_period_percentiles_bottom_of_pack(db):
    bm1 = Bank(name="Banco Uno", bank_type=BankType.banca_multiple)
    bm2 = Bank(name="Banco Dos", bank_type=BankType.banca_multiple)
    db.add_all([bm1, bm2])
    db.flush()
    p = date(2025, 12, 31)
    _rr(db, bm1, p, 40, (40, 40, 40, 40, 40),
        {"solvencia": {"raw": 9.0, "score": 30.0, "available": True}})
    _rr(db, bm2, p, 80, (80, 80, 80, 80, 80),
        {"solvencia": {"raw": 18.0, "score": 95.0, "available": True}})
    db.commit()

    pct = period_percentiles(db, bm1, p)
    # bm1 es el más bajo de 2 → percentil 50 (solo él está <= a su valor)
    assert pct["overall"]["sector"]["percentile"] == 50.0
    assert pct["indicators"]["solvencia"]["sector"]["percentile"] == 50.0


# ── Recorte al corte del informe ──────────────────────────────────────────────
#
# Hallazgo 2026-08-06 (Deep Dive de BPD "al 31-dic-2025"): la trayectoria arrastraba el
# rating REAL de marzo-2026, posterior al período de portada. La narrativa no tiene forma de
# saber qué es esa cifra, así que la racionalizó inventando etiquetas distintas en cada
# sección: "proyectado" en Eficiencia, "preliminar" en Solidez, "histórica y proyectada" en
# Liquidez. La palabra "proyectado" no existe en el código — el motor no proyecta nada.

def test_trajectory_excludes_periods_after_the_cut(db):
    bank = Bank(name="Banco Corte", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    _rr(db, bank, date(2025, 6, 30), 80.0, [80, 80, 80, 80, 80])
    _rr(db, bank, date(2025, 9, 30), 85.0, [85, 85, 85, 85, 85])
    _rr(db, bank, date(2025, 12, 31), 90.0, [90, 90, 90, 90, 90])
    _rr(db, bank, date(2026, 3, 31), 89.9, [89, 89, 89, 89, 89])  # POSTERIOR al corte
    db.commit()

    traj = entity_trajectories(db, bank, as_of=date(2025, 12, 31))
    periodos = [p["period_end"] for p in traj["overall"]]
    assert "2026-03-31" not in periodos, periodos
    assert periodos[-1] == "2025-12-31"
    assert traj["n_periods"] == 3


def test_trajectory_without_as_of_keeps_every_period(db):
    """Sin corte explícito el comportamiento no cambia (otros consumidores)."""
    bank = Bank(name="Banco Libre", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    _rr(db, bank, date(2025, 12, 31), 90.0, [90, 90, 90, 90, 90])
    _rr(db, bank, date(2026, 3, 31), 89.9, [89, 89, 89, 89, 89])
    db.commit()

    periodos = [p["period_end"] for p in entity_trajectories(db, bank)["overall"]]
    assert "2026-03-31" in periodos
