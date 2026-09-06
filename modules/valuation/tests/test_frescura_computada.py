"""La frescura del eje se COMPUTA del dato; un `None` escrito a mano no es neutral.

`data_signals()` devolvía `freshness_days=None` fijo. No es lo mismo que no tener opinión:
el gate de datos penaliza la frescura sin fecha —«no sé de cuándo es» y «está al día» son
cosas distintas, y confundirlas ya costó caro en este repo— así que el eje se llevaba la
mitad de g1 por no declarar algo que sí podía medir. Con la cobertura en 1,00, g1 igual daba
0,50 y el eje quedaba bloqueado.

**Qué corte se mide.** El del BALANCE, no el de la curva. La cadencia del producto es
trimestral porque la Superintendencia publica por trimestre; la curva es mensual y sale de
subastas. Que el plazo largo no se haya colocado el mes pasado no envejece una valuación.
"""
# solo-diciembre: mide la FRESCURA del último corte, no el ROE
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.valuation.products import ValuationProduct
from shared.database.base import Base


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar(db, corte: date) -> None:
    from modules.banking_score.models.models import (
        Bank, BankingData, BankType, DataSource)

    db.add(Bank(id="b1", name="Banco de Prueba", bank_type=BankType.banca_multiple))
    db.add(BankingData(bank_id="b1", period_end=corte, patrimonio_tecnico=1_000.0,
                       utilidad_neta=100.0, source=DataSource.sib_api))
    db.commit()


def test_la_frescura_sale_del_ULTIMO_corte_con_patrimonio(db) -> None:
    hace_67 = date.today() - timedelta(days=67)
    _sembrar(db, hace_67)
    salud = ValuationProduct(db).data_signals()
    assert salud.freshness_days == 67, (
        f"la frescura dio {salud.freshness_days}: tiene que ser la edad del último cierre")


def test_sin_ningun_corte_la_frescura_es_NONE_y_no_cero(db) -> None:
    """Cero días diría «se publicó hoy», que es lo contrario de no tener dato. La ausencia se
    declara como ausencia — es la misma regla que gobierna todo el resto del corpus."""
    salud = ValuationProduct(db).data_signals()
    assert salud.freshness_days is None


def test_la_frescura_NO_se_queda_fija_en_None(db) -> None:
    """El contraejemplo del defecto que se arregla: si alguien vuelve a fijar `None`, este
    test cae aunque haya dato sembrado."""
    _sembrar(db, date.today() - timedelta(days=10))
    salud = ValuationProduct(db).data_signals()
    assert salud.freshness_days is not None, (
        "hay un cierre con patrimonio en la base y la frescura sigue en None: volvió a estar "
        "escrita a mano")
    assert salud.freshness_days == pytest.approx(10, abs=1)


def test_la_cobertura_tambien_se_computa_y_declara_la_curva(db) -> None:
    """Sin la curva son dos insumos de tres, no cero: el balance por entidad está completo, y
    un 0,0 mandaba a arreglar lo que no estaba roto."""
    _sembrar(db, date.today())
    salud = ValuationProduct(db).data_signals()
    assert salud.coverage == pytest.approx(2 / 3), (
        f"cobertura={salud.coverage}: sin la curva tienen que ser dos insumos de tres")
    assert "curva" in salud.detail.lower()
