"""La concentración top-10 se calcula UNA sola vez.

Defecto hallado por el revisor en el Deep Dive de BPD al 2025-12-31: el MISMO documento
reportaba dos valores para el mismo concepto y el mismo corte — 50,90% en Calidad de Activos
y en la tabla de indicadores, 51,5% en Alerta Temprana.

No eran dos criterios metodológicos: era el mismo cálculo escrito dos veces con distinto
denominador. El motor de rating usaba `cartera_total` (con `cartera_bruta` de respaldo); el
de alertas, siempre `cartera_bruta`. Para un comité que lee el PDF una vez, eso no se lee
como diferencia de definición sino como dato inconsistente.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — registra la tabla para la FK
from modules.banking_score.early_warning import _bank_metrics
from modules.banking_score.models.models import Bank, BankingData, BankType
from modules.banking_score.scoring.engine import (
    calc_concentracion_top10,
    concentracion_top10_pct,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_reproduce_la_discrepancia_reportada():
    """Con `cartera_total` ~1,2% mayor que `cartera_bruta` salen los dos valores del informe."""
    d = SimpleNamespace(suma_top10=515.0, cartera_total=1012.0, cartera_bruta=1000.0)
    assert round(concentracion_top10_pct(d), 1) == 50.9      # el del indicador
    assert round(515.0 / 1000.0 * 100, 1) == 51.5            # el que daba Alerta Temprana


def test_el_indicador_y_la_definicion_compartida_coinciden():
    d = SimpleNamespace(suma_top10=515.0, cartera_total=1012.0, cartera_bruta=1000.0)
    assert calc_concentracion_top10(d)["raw"] == round(concentracion_top10_pct(d), 4)


def test_alerta_temprana_usa_la_misma_definicion(db):
    """La red que impide que vuelvan a divergir: ambos motores, un solo número."""
    b = Bank(name="Banco Conc", bank_type=BankType.banca_multiple)
    db.add(b)
    db.flush()
    for per in (date(2024, 12, 31), date(2025, 12, 31)):
        db.add(BankingData(bank_id=b.id, period_end=per, suma_top10=515.0,
                           cartera_total=1012.0, cartera_bruta=1000.0))
    db.commit()

    rows = {r.period_end: r for r in
            db.query(BankingData).filter_by(bank_id=b.id).all()}
    esperado = calc_concentracion_top10(rows[date(2025, 12, 31)])["raw"]

    m = _bank_metrics(rows, date(2025, 12, 31))
    assert m["concentracion_top10_deudores_pct"] == pytest.approx(esperado, abs=0.01)


def test_sin_cartera_total_cae_a_cartera_bruta():
    """El respaldo se conserva: si no hay `cartera_total`, ambas usan `cartera_bruta`."""
    d = SimpleNamespace(suma_top10=515.0, cartera_total=None, cartera_bruta=1000.0)
    assert round(concentracion_top10_pct(d), 1) == 51.5
