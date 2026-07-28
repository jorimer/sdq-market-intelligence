"""Tests de integración del orquestador de alerta temprana (compute_alerts) con DB en
memoria. Ejercitan el cableado completo: umbral de morosidad RELATIVO al tipo, puntaje
ponderado del conjunto, y las dos banderas (deterioro agudo vs zombi crónico)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401 — registra tabla users para resolver FKs
from modules.banking_score.early_warning import bank_alerts, compute_alerts
from modules.banking_score.models.models import Bank, BankingData, BankType
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _quarters(n, end_year=2025):
    """n trimestres consecutivos terminando en dic de end_year."""
    out = []
    y, m = end_year, 12
    for _ in range(n):
        out.append(date(y, m, 28))
        m -= 3
        if m <= 0:
            m, y = 12, y - 1
    return sorted(out)


def _bank(db, name, btype):
    b = Bank(name=name, bank_type=btype, is_active=True)
    db.add(b)
    db.flush()
    return b


def _obs(db, bank, period, *, mora, cob, solv, dep=600.0):
    db.add(BankingData(bank_id=bank.id, period_end=period, morosidad_pct=mora,
                       cobertura_pct=cob, solvencia_pct=solv, activos_totales=1000.0,
                       depositos_totales=dep))


def test_perfil_agudo_score_y_banderas(db):
    """Banco múltiple sano que se deteriora en el último año → perfil AGUDO, score alto,
    con las señales de nivel + salto + cobertura + erosión de capital."""
    qs = _quarters(9)
    b = _bank(db, "Banco Deterioro", BankType.banca_multiple)
    for q in qs[:-3]:
        _obs(db, b, q, mora=2.0, cob=160.0, solv=14.0)      # sano 1.5 años
    for q in qs[-3:]:
        _obs(db, b, q, mora=13.0, cob=45.0, solv=9.5)       # deterioro agudo reciente
    db.commit()

    entry = bank_alerts(db, b.id)
    assert entry["perfil"] == "agudo"
    assert entry["band"] == "alta" and entry["score"] > 55
    codes = {a["code"] for a in entry["alerts"]}
    assert {"morosidad_nivel", "salto_morosidad", "brecha_provisiones", "erosion_capital"} <= codes


def test_perfil_cronico_zombi(db):
    """Morosidad alta SOSTENIDA (podrido ≥2 años, sin salto ni erosión nuevos) → CRÓNICO."""
    qs = _quarters(9)
    b = _bank(db, "Banco Zombi", BankType.banca_multiple)
    for q in qs:
        _obs(db, b, q, mora=12.0, cob=55.0, solv=10.0)      # plano y enfermo todo el tramo
    db.commit()

    entry = bank_alerts(db, b.id)
    assert entry["perfil"] == "cronico"
    codes = {a["code"] for a in entry["alerts"]}
    assert "morosidad_nivel" in codes
    assert "salto_morosidad" not in codes                    # sin salto: no es deterioro nuevo


def test_umbral_morosidad_relativo_al_tipo(db):
    """La misma morosidad (10%) marca al banco múltiple (umbral 5) pero NO a la corporación
    de crédito (umbral 15) — el umbral es relativo al tipo de entidad."""
    qs = _quarters(9)
    mult = _bank(db, "Múltiple 10pct", BankType.banca_multiple)
    corp = _bank(db, "Corporación 10pct", BankType.corporacion_credito)
    for q in qs:
        _obs(db, mult, q, mora=10.0, cob=160.0, solv=14.0)
        _obs(db, corp, q, mora=10.0, cob=160.0, solv=14.0)
    db.commit()

    block = compute_alerts(db)
    by_name = {b["name"]: b for b in block["banks"]}
    assert "Múltiple 10pct" in by_name                       # marcado por nivel
    assert "morosidad_nivel" in {a["code"] for a in by_name["Múltiple 10pct"]["alerts"]}
    # la corporación al 10% NO dispara nivel de morosidad (su normal es más alto)
    corp_entry = by_name.get("Corporación 10pct")
    if corp_entry is not None:
        assert "morosidad_nivel" not in {a["code"] for a in corp_entry["alerts"]}


def test_banco_sano_no_aparece(db):
    qs = _quarters(9)
    b = _bank(db, "Banco Sano", BankType.banca_multiple)
    for q in qs:
        _obs(db, b, q, mora=2.0, cob=180.0, solv=15.0)
    db.commit()

    block = compute_alerts(db)
    assert all(x["name"] != "Banco Sano" for x in block["banks"])
    entry = bank_alerts(db, b.id)
    assert entry["alerts"] == [] and entry["perfil"] is None
