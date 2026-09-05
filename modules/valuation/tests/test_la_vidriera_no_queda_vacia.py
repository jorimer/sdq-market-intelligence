"""Un producto publicable tiene que poder PEDIRSE: períodos y entidades reales.

`available_periods()` devolvía `[]` y `scope_options` no existía. Con readiness en 0,85 el eje
quedaba «publicable» y el selector no ofrecía nada: el producto se listaba y no se podía
pedir. **El gate de readiness no ve esto** — mide insumos (dato, motor, prosa, validación), no
la entrega—, así que un eje puede cruzar su umbral con la vidriera vacía.

Y las dos listas tienen la misma regla: se ofrece lo que PRODUCE. Una opción que falla al
elegirla es peor que no ofrecerla, porque el que la eligió ya pagó la vuelta.
"""
from datetime import date

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


def _entidad(db, ident: str, nombre: str, cierres: int, tipo=None) -> None:
    from modules.banking_score.models.models import (
        Bank, BankingData, BankType, DataSource)

    db.add(Bank(id=ident, name=nombre, bank_type=tipo or BankType.banca_multiple))
    for i in range(cierres):
        db.add(BankingData(bank_id=ident, period_end=date(2022 + i, 12, 31),
                           patrimonio_tecnico=1_000_000.0 * (1.05 ** i),
                           utilidad_neta=100_000.0, source=DataSource.sib_api))
    db.commit()


def test_una_entidad_con_UN_solo_cierre_no_se_ofrece(db) -> None:
    """El ROE va sobre patrimonio de APERTURA: con un cierre no hay con qué computarlo, y
    `snapshot` lo rechaza. Ofrecerla sería una opción que falla al elegirla."""
    _entidad(db, "b1", "Banco de Un Cierre", cierres=1)
    assert ValuationProduct(db).scope_options() == []


def test_una_entidad_con_DOS_cierres_si_se_ofrece(db) -> None:
    _entidad(db, "b2", "Banco Valuable", cierres=2)
    opciones = ValuationProduct(db).scope_options()
    assert [o["value"] for o in opciones] == ["b2"]
    assert opciones[0]["label"] == "Banco Valuable"


def test_los_periodos_NO_ofrecen_el_corte_mas_viejo(db) -> None:
    """Contra el primer corte ninguna entidad tiene apertura: ofrecerlo garantiza el error."""
    _entidad(db, "b3", "Banco Valuable", cierres=3)
    periodos = ValuationProduct(db).available_periods()
    assert periodos, "el selector quedó vacío con tres cierres sembrados"
    assert "2022-12-31" not in periodos, (
        "se ofrece el corte más viejo, contra el que no hay patrimonio de apertura")
    assert periodos[0] == "2024-12-31", f"el más reciente primero: {periodos}"


def test_sin_NINGUN_dato_las_dos_listas_estan_vacias(db) -> None:
    """Vacío por ausencia de dato es correcto; lo que no puede ser es vacío por estar escrito
    a mano, que es de lo que se sale acá."""
    p = ValuationProduct(db)
    assert p.available_periods() == [] and p.scope_options() == []


def test_las_listas_NO_estan_escritas_a_mano(db) -> None:
    """El contraejemplo del defecto: con dato sembrado, las dos tienen que responder."""
    _entidad(db, "b4", "Banco Valuable", cierres=3)
    p = ValuationProduct(db)
    assert p.available_periods(), "`available_periods` volvió a devolver una lista fija"
    assert p.scope_options(), "`scope_options` volvió a devolver una lista fija"


def test_una_CAMBIARIA_no_se_ofrece_aunque_tenga_todo_el_dato(db) -> None:
    """El caso que el selector de producción destapó: 41 de las 92 entidades ofrecidas eran
    agentes de cambio y casas de remesas.

    No es falta de dato — tienen patrimonio y utilidad, la aritmética corre y devuelve un
    número de aspecto perfectamente normal. Lo que no tienen es el negocio que el modelo
    supone: el Excess Return descuenta el exceso de ROE sobre el costo de capital de una
    entidad que toma depósitos y presta, y el panel de múltiplos contra el que se
    contrastaría son bancos.

    **Que el resultado no se vea mal es lo que lo hace peligroso**: una opción que falla al
    elegirla se descubre sola; una que devuelve un número sin sentido, no.
    """
    from modules.banking_score.models.models import BankType

    _entidad(db, "cx", "Agc Damos", cierres=4, tipo=BankType.cambiaria)
    assert ValuationProduct(db).scope_options() == []


def test_una_ASOCIACION_de_ahorros_y_prestamos_SI_se_ofrece(db) -> None:
    """El contraejemplo que impide filtrar de más. Son entidades de intermediación
    supervisadas; que sean mutuales —sin acciones que comprar— es un caveat del informe, no
    un motivo para no poder valuarlas."""
    from modules.banking_score.models.models import BankType

    _entidad(db, "aap1", "Asociación Cibao de Ahorros y Préstamos", cierres=3,
             tipo=BankType.aap)
    assert [o["value"] for o in ValuationProduct(db).scope_options()] == ["aap1"]


def test_el_TIPO_viaja_con_la_entidad_en_el_selector(db) -> None:
    """El sujeto viaja con el número: quien elige tiene que ver de qué tipo es la entidad,
    porque un banco múltiple y una asociación no se leen igual."""
    from modules.banking_score.models.models import BankType

    _entidad(db, "aap2", "Asociación Popular", cierres=3, tipo=BankType.aap)
    opciones = ValuationProduct(db).scope_options()
    assert opciones[0]["group"] == "aap", (
        f"el selector no dice el tipo: group={opciones[0]['group']!r}")
