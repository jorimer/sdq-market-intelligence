"""El almacén regional guarda lo que se le da, y declara lo que le falta.

Lo que estos tests protegen no es el ORM sino dos reglas de la casa que este modelo existe
para sostener: un dato ausente se persiste como ausente, y una métrica no se puede comparar
entre países sin saber bajo qué norma la computó cada uno.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.regional_banking.models.models import CountryBankingAggregate
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine, autoflush=False)()
    yield sesion
    sesion.close()


def _fila(**kw):
    base = dict(iso_code="COL", period_end=dt.date(2026, 6, 30), metric="solvencia",
                value=17.4, source="SFC", license="CC BY-SA 4.0",
                norma_contable="CUIF Colombia (SFC)")
    base.update(kw)
    return CountryBankingAggregate(**base)


def test_un_valor_ausente_persiste_como_ausente(db):
    """`None` no es `0.0`. En un ratio de solvencia, cero es una entidad quebrada.

    Es el criterio de aceptación de T-BR-4 y la doctrina de la casa: se declara la brecha,
    no se rellena.
    """
    db.add(_fila(value=None, metric="cobertura_provisiones"))
    db.commit()
    db.expunge_all()

    fila = db.query(CountryBankingAggregate).filter_by(metric="cobertura_provisiones").one()
    assert fila.value is None
    assert fila.value != 0.0


def test_la_misma_metrica_de_dos_fuentes_NO_colapsa(db):
    """`source` está en la clave única a propósito.

    RD llega por dos caminos —EMFA armonizado junto a otros siete países, y la SB— y cada
    uno trae su propia `norma_contable`. Sin `source` en la clave, uno pisaría al otro y lo
    que se perdería no sería un duplicado sino una medición distinta.
    """
    db.add(_fila(iso_code="DOM", metric="credito_total", source="SECMCA",
                 norma_contable="EMFA armonizado", value=100.0))
    db.add(_fila(iso_code="DOM", metric="credito_total", source="SB",
                 norma_contable="SB — plan de cuentas RD", value=98.0))
    db.commit()

    filas = db.query(CountryBankingAggregate).filter_by(iso_code="DOM").all()
    assert len(filas) == 2
    assert {f.norma_contable for f in filas} == {"EMFA armonizado", "SB — plan de cuentas RD"}


def test_no_se_repite_la_misma_medicion(db):
    """La misma (país, corte, métrica, fuente) dos veces sí es un duplicado."""
    db.add(_fila())
    db.commit()
    db.add(_fila(value=99.9))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("campo", ["norma_contable", "license", "source"])
def test_la_procedencia_es_obligatoria(db, campo):
    """Sin norma no hay comparabilidad, y sin licencia no se publica: fail-closed.

    Se prueban los tres juntos porque los tres son la misma decisión — que la fila no
    pueda existir sin decir de dónde viene y bajo qué regla se computó.
    """
    db.add(_fila(**{campo: None}))
    with pytest.raises(IntegrityError):
        db.commit()


def test_el_corte_es_una_fecha_no_una_etiqueta(db):
    """`period_end` es `Date` y no `String(10)` como en `CountryVariable`.

    Los cuatro países publican con cortes distintos —Chile a ~28 días, Brasil a ~6 meses—
    y el boletín declara el corte por país. Una etiqueta de texto no se puede ordenar ni
    comparar entre calendarios sin parsearla en cada uso.
    """
    db.add(_fila(period_end=dt.date(2026, 3, 31)))
    db.commit()
    db.expunge_all()
    assert db.query(CountryBankingAggregate).one().period_end == dt.date(2026, 3, 31)
