"""Tests del crosswalk histórico SIB (ledger → financials derivados)."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.banking_score.models.models import (
    SibHistoricalFinancials,
    SibHistoricalLedger,
)
from modules.banking_score import sib_historical_crosswalk as xw


def _bal(n1, n2, n3, monto, **meta):
    base = dict(estado="situacion", entidad_code="BPOP", entidad_nombre="Banco Popular",
                tipo_entidad="Bancos Múltiples", sector="Privado", fecha=date(2023, 12, 1),
                ano=2023, mes=12, nivel_4=None, snapshot_date=date(2026, 7, 19))
    base.update(meta)
    return SimpleNamespace(nivel_1=n1, nivel_2=n2, nivel_3=n3, monto=monto, **base)


def _pl(n1, monto):
    return SimpleNamespace(estado="resultados", entidad_code="BPOP", entidad_nombre="Banco Popular",
                           tipo_entidad="Bancos Múltiples", sector="Privado", fecha=date(2023, 12, 1),
                           ano=2023, mes=12, nivel_1=n1, nivel_2=n1, nivel_3=None, nivel_4=None,
                           monto=monto, snapshot_date=date(2026, 7, 19))


# ── Pure crosswalk ────────────────────────────────────────────────────

def test_derive_group_balance_and_ratios():
    rows = [
        _bal("Activos", "Total", "Total", 1_000.0),
        _bal("Pasivos", "Total", "Total", 850.0),
        _bal("Patrimonio", "Total", "Total", 150.0),
        _bal("Pasivos", "Depósitos del público", "Depósitos del público", 600.0),
        _bal("Activos", "Inversiones", "Inversiones", 120.0),
        _bal("Activos", "Efectivo y equivalentes de efectivo", "Efectivo y equivalentes de efectivo", 80.0),
        # cartera: bruta = vigentes + vencida + cobranza judicial; provisiones aparte (negativa)
        _bal("Activos", "Cartera de créditos", "Vigentes", 900.0),
        _bal("Activos", "Cartera de créditos", "Vencida (más de 90 días)", 30.0),
        _bal("Activos", "Cartera de créditos", "Cobranza judicial", 10.0),
        _bal("Activos", "Cartera de créditos", "En mora (de 31 a 90 días)", 20.0),
        _bal("Activos", "Cartera de créditos", "Provisiones para créditos", -50.0),
    ]
    d = xw.derive_group(rows)
    assert d["activos_totales"] == 1_000.0
    assert d["patrimonio"] == 150.0
    assert d["depositos_totales"] == 600.0
    assert d["activos_liquidos"] == 200.0           # 120 + 80
    assert d["cartera_bruta"] == 960.0              # 900 + 30 + 10 + 20 (excluye provisiones)
    assert d["cartera_vencida_90d"] == 40.0         # 30 + 10 (NO la mora 31-90)
    assert d["provisiones"] == 50.0                 # abs
    assert d["cartera_neta"] == 910.0               # 960 - 50
    # ratios
    assert d["morosidad_pct"] == pytest.approx(100 * 40 / 960, abs=1e-4)
    assert d["cobertura_pct"] == pytest.approx(100 * 50 / 40, abs=1e-4)
    assert d["apalancamiento_pct"] == pytest.approx(100 * 150 / 1000, abs=1e-4)


def test_derive_group_pl_fields():
    rows = [
        _bal("Activos", "Total", "Total", 1_000.0),
        _pl("Resultado del ejercicio", 42.0),
        _pl("Ingresos financieros", 130.0),
        _pl("Gastos financieros", -30.0),
        _pl("Gastos operativos", -72.0),
        _pl("Margen financiero bruto", 50.0),
    ]
    d = xw.derive_group(rows)
    assert d["utilidad_neta"] == 42.0
    assert d["ingresos_financieros"] == 130.0
    assert d["gastos_operativos"] == -72.0
    assert d["margen_financiero_bruto"] == 50.0


def test_derive_group_missing_estado_leaves_none():
    """Un grupo con solo P&L deja los campos de balance en None (no 0 espurio)."""
    d = xw.derive_group([_pl("Resultado del ejercicio", 5.0)])
    assert d["utilidad_neta"] == 5.0
    assert d["activos_totales"] is None
    assert d["morosidad_pct"] is None


# ── End-to-end sobre DB ───────────────────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[SibHistoricalLedger.__table__, SibHistoricalFinancials.__table__],
    )
    return sessionmaker(bind=engine)()


def _ins(db, **kw):
    base = dict(estado="situacion", entidad_code="BPOP", entidad_nombre="Banco Popular",
                tipo_entidad="Bancos Múltiples", sector="Privado", ano=2023, mes=12,
                nivel_3=None, nivel_4=None, monto=None, snapshot_date=date(2026, 7, 19),
                row_key=None)
    base.update(kw)
    base["row_key"] = base["row_key"] or f"{base['estado']}|{base['fecha']}|{base['nivel_1']}|{base['nivel_2']}|{base['nivel_3']}"
    db.add(SibHistoricalLedger(**base))


def test_derive_all_end_to_end(db):
    _ins(db, fecha=date(2023, 12, 1), nivel_1="Activos", nivel_2="Total", nivel_3="Total", monto=1000)
    _ins(db, fecha=date(2023, 12, 1), nivel_1="Patrimonio", nivel_2="Total", nivel_3="Total", monto=150)
    _ins(db, fecha=date(2023, 11, 1), nivel_1="Activos", nivel_2="Total", nivel_3="Total", monto=980)
    db.commit()
    n = xw.derive_all(db)
    assert n == 2  # dos períodos
    dec = db.query(SibHistoricalFinancials).filter_by(fecha=date(2023, 12, 1)).one()
    assert float(dec.activos_totales) == 1000
    assert float(dec.apalancamiento_pct) == pytest.approx(15.0, abs=1e-4)
    # idempotencia: recorrer de nuevo no duplica
    xw.derive_all(db)
    assert db.query(SibHistoricalFinancials).count() == 2


def test_reconcile_entity(db):
    from shared.auth.models import User  # noqa: F401 — banking_data.uploaded_by FK → users
    from modules.banking_score.models.models import Bank, BankType, BankingData
    Base.metadata.create_all(
        db.get_bind(), tables=[User.__table__, Bank.__table__, BankingData.__table__]
    )
    bank = Bank(name="Banco Popular", bank_type=BankType.banca_multiple)
    db.add(bank)
    db.flush()
    db.add(BankingData(bank_id=bank.id, period_end=date(2023, 12, 1), activos_totales=1000))
    db.add(SibHistoricalFinancials(entidad_code="BPOP", fecha=date(2023, 12, 1), ano=2023, mes=12,
                                   activos_totales=1015))  # +1.5%
    db.commit()
    rep = xw.reconcile_entity(db, "BPOP", bank.id, tol=0.02)
    assert len(rep) == 1
    assert rep[0]["ok"] is True  # 1.5% < 2%
    assert rep[0]["rel_diff"] == pytest.approx(0.015, abs=1e-3)
