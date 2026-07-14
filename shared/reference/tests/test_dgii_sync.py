"""Tests del sync del padrón DGII → tabla, con historia multi-corte.

Valida: el upsert por (corte, subclase) no duplica al re-correr el mismo corte; un corte
nuevo ACUMULA (no pisa) y ``latest_*`` devuelve el más reciente. Inyecta un cliente falso
para controlar corte/filas sin depender de red ni del Excel."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.dgii_rnc_client import SubclaseContrib
from shared.data.lineage import Lineage
from shared.database.base import Base
from shared.reference.dgii_query import latest_contribuyentes, latest_corte
from shared.reference.dgii_sync import dgii_contribuyentes_sync
from shared.reference.models import DgiiContribuyenteSubclase


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[DgiiContribuyenteSubclase.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _FakeClient:
    """Devuelve un corte/filas fijos (evita red y Excel)."""

    def __init__(self, corte, rows):
        self._corte, self._rows = corte, rows

    def fetch_aggregates(self):
        lin = Lineage(source="DGII", license="pública", published_at=self._corte,
                      fetched_at=date.today(), url="http://x", note="caveat")
        return self._corte, self._rows, lin


def _rows(**kw):
    return [SubclaseContrib(code, "d", act, 0, act) for code, act in kw.items()]


def test_sync_inserta_y_query_devuelve(db):
    res = dgii_contribuyentes_sync(db, client=_FakeClient(
        date(2026, 1, 29), _rows(**{"552118": 1966, "551101": 1897})))
    assert res == {"corte": "2026-01-29", "subclases": 2, "touched": 2}
    corte, by = latest_contribuyentes(db)
    assert corte == date(2026, 1, 29)
    assert by["552118"].activos == 1966


def test_rerun_mismo_corte_no_duplica(db):
    c = _FakeClient(date(2026, 1, 29), _rows(**{"552118": 1966}))
    dgii_contribuyentes_sync(db, client=c)
    dgii_contribuyentes_sync(db, client=_FakeClient(  # mismo corte, valor corregido
        date(2026, 1, 29), _rows(**{"552118": 2000})))
    n = db.query(DgiiContribuyenteSubclase).count()
    assert n == 1                                        # upsert, no duplica
    _, by = latest_contribuyentes(db)
    assert by["552118"].activos == 2000                 # se actualizó


def test_corte_nuevo_acumula_historia(db):
    dgii_contribuyentes_sync(db, client=_FakeClient(
        date(2026, 1, 29), _rows(**{"552118": 1966})))
    dgii_contribuyentes_sync(db, client=_FakeClient(
        date(2026, 7, 30), _rows(**{"552118": 2100})))
    assert db.query(DgiiContribuyenteSubclase).count() == 2   # ambos cortes viven
    assert latest_corte(db) == date(2026, 7, 30)
    _, by = latest_contribuyentes(db)
    assert by["552118"].activos == 2100                       # el último corte
