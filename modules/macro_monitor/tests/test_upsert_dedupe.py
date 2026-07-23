"""Un valor real nunca puede ser pisado por un vacío del mismo lote.

Defecto real: ``Remesas_6.xlsx`` trae columnas de relleno a la derecha del último año.
El extractor emite el valor real y después dos celdas vacías para el MISMO período; el
dedupe "último gana" ingenuo dejaba 12 de 204 períodos en None — borrando dato publicado
por el BCRD. No fabricar y no destruir son la misma disciplina.
"""
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.macro_monitor.service import _upsert_records
from shared.database.base import Base


@dataclass
class _Rec:
    series: str
    period: str
    value: Optional[float]
    unit: Optional[str] = None
    lineage: Any = None


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _value(db, code, period):
    return db.query(MacroSeries).filter_by(series_code=code, period=period).one().value


def test_a_trailing_null_never_erases_a_real_value(db):
    _upsert_records(db, [
        _Rec("remesas", "2026-06", 1049250048.08),
        _Rec("remesas", "2026-06", None),          # columna de relleno
        _Rec("remesas", "2026-06", None),
    ])
    assert _value(db, "remesas", "2026-06") == 1049250048.08


def test_a_real_value_still_wins_when_it_comes_last(db):
    """La regla no es 'primero gana': es 'un valor real le gana a un vacío'."""
    _upsert_records(db, [
        _Rec("remesas", "2026-07", None),
        _Rec("remesas", "2026-07", 999.0),
    ])
    assert _value(db, "remesas", "2026-07") == 999.0


def test_two_real_values_keep_last_wins(db):
    """Entre dos valores reales se conserva el comportamiento previo (último gana):
    es la semántica del upsert por fila y no hay razón para cambiarla."""
    _upsert_records(db, [
        _Rec("remesas", "2026-08", 1.0),
        _Rec("remesas", "2026-08", 2.0),
    ])
    assert _value(db, "remesas", "2026-08") == 2.0


def test_an_all_null_period_stays_null(db):
    """Si la fuente no publicó nada, el período queda en None — no se inventa un cero."""
    _upsert_records(db, [
        _Rec("remesas", "2026-09", None),
        _Rec("remesas", "2026-09", None),
    ])
    assert _value(db, "remesas", "2026-09") is None
