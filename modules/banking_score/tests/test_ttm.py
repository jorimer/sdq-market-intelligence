"""ROA y ROE se miden sobre la ventana móvil de 12 MESES, no sobre el acumulado anualizado.

El motor anualizaba multiplicando por ``12/mes``, lo que asume que todos los trimestres pesan
igual. El panel lo refuta: sobre 71 banco-años de 16 bancos múltiples (2021-2025) el PRIMER
TRIMESTRE concentra una mediana de 9,9% de la utilidad anual (97% de los casos bajo 20%),
mientras Q2/Q3/Q4 aportan ~30% cada uno. Multiplicar ×4 un trimestre que vale 9,9% proyecta
~40% de la tasa real: BPD marcaba ROE 10,2% al Q1 contra 24,2% al cierre, con el score
cayendo de 100 a 68 sin ningún cambio de negocio.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — registra la tabla para la FK
from modules.banking_score.models.models import Bank, BankingData, BankType
from modules.banking_score.scoring.engine import (
    BankingDataInput, calc_roa, calc_roe, calculate_all_indicators,
)


def _entrada(*, utilidad, ttm=None, period=None):
    """Entrada COMPLETA del motor (el dataclass trae defaults) + los campos extra."""
    d = BankingDataInput(utilidad_neta=utilidad, activos_promedio=1000.0,
                         patrimonio_promedio=100.0)
    if ttm is not None:
        d.utilidad_ttm = ttm
    if period is not None:
        d.period_end = period
    return d
from modules.banking_score.scoring.ttm import attach_ttm, utilidad_ttm


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _data(db, bank, period, utilidad):
    db.add(BankingData(bank_id=bank.id, period_end=period, utilidad_neta=utilidad,
                       activos_promedio=1000.0, patrimonio_promedio=100.0))
    db.commit()


@pytest.fixture()
def bank(db):
    b = Bank(name="Banco TTM", bank_type=BankType.banca_multiple)
    db.add(b)
    db.commit()
    return b


# ── El cálculo de la ventana ──────────────────────────────────────────────────

def test_en_diciembre_el_acumulado_ya_es_la_ventana(db, bank):
    """Cierre de ejercicio: no hace falta historia."""
    _data(db, bank, date(2025, 12, 31), 100.0)
    assert utilidad_ttm(db, bank.id, date(2025, 12, 31)) == 100.0


def test_corte_intermedio_usa_la_ventana_movil(db, bank):
    """TTM(Q1-2026) = acum(Q1-2026) + ejercicio 2025 − acum(Q1-2025).

    Con el reparto REAL del panel (Q1 ≈ 10% del año): un Q1 de 10 sobre un ejercicio previo
    de 100 con Q1 previo de 10 da una ventana de 100 — la MISMA tasa anual que el cierre.
    Ese es el punto: el diente de sierra desaparece por construcción.
    """
    _data(db, bank, date(2025, 3, 31), 10.0)
    _data(db, bank, date(2025, 12, 31), 100.0)
    _data(db, bank, date(2026, 3, 31), 10.0)
    assert utilidad_ttm(db, bank.id, date(2026, 3, 31)) == 100.0


def test_la_ventana_capta_la_mejora_real(db, bank):
    """Si el Q1 nuevo supera al del año previo, la ventana sube — el método sigue midiendo."""
    _data(db, bank, date(2025, 3, 31), 10.0)
    _data(db, bank, date(2025, 12, 31), 100.0)
    _data(db, bank, date(2026, 3, 31), 25.0)
    assert utilidad_ttm(db, bank.id, date(2026, 3, 31)) == 115.0


def test_sin_historia_no_hay_ventana(db, bank):
    """Primer año de una entidad: no se computa."""
    _data(db, bank, date(2026, 3, 31), 10.0)
    assert utilidad_ttm(db, bank.id, date(2026, 3, 31)) is None


def test_falta_el_cierre_previo(db, bank):
    _data(db, bank, date(2025, 3, 31), 10.0)
    _data(db, bank, date(2026, 3, 31), 10.0)
    assert utilidad_ttm(db, bank.id, date(2026, 3, 31)) is None


# ── El motor ──────────────────────────────────────────────────────────────────

def test_sin_ventana_roa_y_roe_se_declaran_no_disponibles():
    """Decisión del dueño: NO se cae al método viejo. Un número calculado sobre un supuesto
    refutado es peor que un hueco declarado."""
    ind = calculate_all_indicators(_entrada(utilidad=10.0, period=date(2026, 3, 31)))
    assert ind["roa"]["available"] is False
    assert ind["roe"]["available"] is False


def test_con_ventana_se_calculan_y_quedan_disponibles():
    ind = calculate_all_indicators(
        _entrada(utilidad=10.0, ttm=100.0, period=date(2026, 3, 31)))
    assert ind["roa"]["available"] is True
    assert ind["roa"]["raw"] == 10.0     # 100/1000
    assert ind["roe"]["raw"] == 100.0    # 100/100


def test_desaparece_el_diente_de_sierra():
    """Mismo negocio en Q1 y en el cierre → MISMA tasa. Antes: Q1 daba ~40% del cierre."""
    cierre = _entrada(utilidad=100.0, period=date(2025, 12, 31))
    q1 = _entrada(utilidad=10.0, ttm=100.0, period=date(2026, 3, 31))
    assert calc_roa(q1)["raw"] == calc_roa(cierre)["raw"]
    assert calc_roe(q1)["raw"] == calc_roe(cierre)["raw"]
    assert calc_roe(q1)["score"] == calc_roe(cierre)["score"]


def test_el_contexto_sintetico_sin_periodo_no_cambia():
    """Muestras y tests sin `period_end` conservan el comportamiento anual histórico."""
    d = _entrada(utilidad=100.0)
    assert calc_roa(d)["raw"] == 10.0
    assert calculate_all_indicators(d)["roa"]["available"] is True


def test_attach_ttm_no_revienta_sin_dato(db, bank):
    rec = SimpleNamespace(bank_id=bank.id, period_end=date(2026, 3, 31))
    attach_ttm(db, rec)
    assert rec.utilidad_ttm is None
