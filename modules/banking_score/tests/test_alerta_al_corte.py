"""Las alertas de un informe son las de SU corte, no las del último período disponible.

Defecto reportado por el revisor: el Deep Dive de BPD "al 31-dic-2025" mostraba la
concentración top-10 en 50,90% (§Calidad de Activos y tabla de indicadores) y en 51,5%
(§10 Alerta Temprana). Se leyó —razonablemente— como dos definiciones distintas.

NO lo era. La serie del propio motor lo prueba: 50,8989 al 2025-12-31 y 51,4932 al
2026-03-31. Misma métrica, misma fórmula, DOS FECHAS: `bank_alerts` no recibía el corte del
informe y caía al último período con dato. Misma familia que la trayectoria (#635) y las
capas de contexto (#637): el corte manda sobre todo lo que el informe muestra.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User  # noqa: F401 — registra la tabla para la FK
from modules.banking_score.early_warning import bank_alerts, compute_alerts
from modules.banking_score.models.models import Bank, BankingData, BankType


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


@pytest.fixture()
def bank(db):
    """Un banco con concentración creciente: 50,9% en dic-2025 y 51,5% en mar-2026."""
    b = Bank(name="Banco Corte", bank_type=BankType.banca_multiple, is_active=True)
    db.add(b)
    db.flush()
    for per, top10 in ((date(2025, 12, 31), 509.0), (date(2026, 3, 31), 515.0)):
        db.add(BankingData(bank_id=b.id, period_end=per, suma_top10=top10,
                           cartera_total=1000.0, cartera_bruta=1000.0,
                           activos_totales=5000.0, depositos_totales=4000.0))
    db.commit()
    return b


def _conc(block):
    return next((a["value"] for a in block["alerts"] if a["code"] == "concentracion"), None)


def test_las_alertas_son_las_del_corte_pedido(db, bank):
    """El informe de diciembre debe ver la concentración de DICIEMBRE."""
    block = bank_alerts(db, bank.id, date(2025, 12, 31))
    assert str(block["period"]) == "2025-12-31"
    assert _conc(block) == 50.9


def test_sin_corte_sigue_cayendo_al_ultimo(db, bank):
    """Compatibilidad: el endpoint del sistema no pasa período y ve el más reciente."""
    assert _conc(bank_alerts(db, bank.id)) == 51.5


def test_el_informe_de_diciembre_no_muestra_marzo(db, bank):
    """La regresión exacta que reportó el revisor: dos cifras del mismo concepto en un
    mismo documento, que en realidad eran dos fechas."""
    dic = _conc(bank_alerts(db, bank.id, date(2025, 12, 31)))
    mar = _conc(bank_alerts(db, bank.id, date(2026, 3, 31)))
    assert dic != mar
    assert dic == 50.9 and mar == 51.5


def test_compute_alerts_respeta_el_periodo(db, bank):
    assert str(compute_alerts(db, date(2025, 12, 31))["period"]) == "2025-12-31"
