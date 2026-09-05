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


def _entidad(db, ident: str, nombre: str, cierres: int) -> None:
    from modules.banking_score.models.models import (
        Bank, BankingData, BankType, DataSource)

    db.add(Bank(id=ident, name=nombre, bank_type=BankType.banca_multiple))
    for i in range(cierres):
        db.add(BankingData(bank_id=ident, period_end=date(2022 + i, 12, 31),
                           patrimonio_tecnico=1_000_000.0 * (1.05 ** i),
                           utilidad_neta=100_000.0, source=DataSource.sib_api))
    db.commit()


def test_una_entidad_con_UN_solo_cierre_no_se_ofrece(db):
    """El ROE va sobre patrimonio de APERTURA: con un cierre no hay con qué computarlo, y
    `snapshot` lo rechaza. Ofrecerla sería una opción que falla al elegirla."""
    _entidad(db, "b1", "Banco de Un Cierre", cierres=1)
    assert ValuationProduct(db).scope_options() == []


def test_una_entidad_con_DOS_cierres_si_se_ofrece(db):
    _entidad(db, "b2", "Banco Valuable", cierres=2)
    opciones = ValuationProduct(db).scope_options()
    assert [o["value"] for o in opciones] == ["b2"]
    assert opciones[0]["label"] == "Banco Valuable"


def test_los_periodos_NO_ofrecen_el_corte_mas_viejo(db):
    """Contra el primer corte ninguna entidad tiene apertura: ofrecerlo garantiza el error."""
    _entidad(db, "b3", "Banco Valuable", cierres=3)
    periodos = ValuationProduct(db).available_periods()
    assert periodos, "el selector quedó vacío con tres cierres sembrados"
    assert "2022-12-31" not in periodos, (
        "se ofrece el corte más viejo, contra el que no hay patrimonio de apertura")
    assert periodos[0] == "2024-12-31", f"el más reciente primero: {periodos}"


def test_sin_NINGUN_dato_las_dos_listas_estan_vacias(db):
    """Vacío por ausencia de dato es correcto; lo que no puede ser es vacío por estar escrito
    a mano, que es de lo que se sale acá."""
    p = ValuationProduct(db)
    assert p.available_periods() == [] and p.scope_options() == []


def test_las_listas_NO_estan_escritas_a_mano(db):
    """El contraejemplo del defecto: con dato sembrado, las dos tienen que responder."""
    _entidad(db, "b4", "Banco Valuable", cierres=3)
    p = ValuationProduct(db)
    assert p.available_periods(), "`available_periods` volvió a devolver una lista fija"
    assert p.scope_options(), "`scope_options` volvió a devolver una lista fija"
