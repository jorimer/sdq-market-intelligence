"""Regresión E2E-SYS2/PN1: ``dimension_trend`` da trayectoria a las dimensiones DERIVADAS
del ISA (solvencia/costo = ratio período-a-período; riesgo = NAV), que antes salían con
``trend=[]``. rentabilidad/escala (métrica directa) siguen igual.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.models.models import PensionSeries
from modules.pension_intel.scoring.isa import dimension_trend
from modules.pension_intel.nav_sync import VALOR_CUOTA_CODE


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[PensionSeries.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _add(db, slug, code, points):
    for period, value in points:
        db.add(PensionSeries(entity_slug=slug, series_code=code, period=period, value=value))
    db.commit()


def test_solvencia_ratio_trajectory(db):
    # patrimonio/activos por período → ratio en % alineado por período común.
    _add(db, "afp_x", "patrimonio", [("2025-06", 40.0), ("2025-12", 50.0), ("2026-06", 60.0)])
    _add(db, "afp_x", "activos_totales", [("2025-06", 400.0), ("2025-12", 400.0), ("2026-06", 400.0)])
    trend = dimension_trend(db, "afp_x", "solvencia")
    assert [p for p, _ in trend] == ["2025-06", "2025-12", "2026-06"]
    assert [v for _, v in trend] == [10.0, 12.5, 15.0]  # 40/400, 50/400, 60/400 en %


def test_costo_ratio_only_common_periods(db):
    _add(db, "afp_x", "comisiones_anual", [("2025-12", 10.0), ("2026-06", 12.0)])
    _add(db, "afp_x", "fondos_administrados", [("2025-06", 999.0), ("2025-12", 100.0), ("2026-06", 100.0)])
    trend = dimension_trend(db, "afp_x", "costo")
    # solo períodos con AMBOS componentes (2025-06 no tiene comisiones).
    assert [p for p, _ in trend] == ["2025-12", "2026-06"]
    assert [v for _, v in trend] == [10.0, 12.0]


def test_rentabilidad_direct_metric(db):
    _add(db, "afp_x", "rentabilidad_nominal_anual", [("2025-12", 7.5), ("2026-06", 8.0)])
    assert dimension_trend(db, "afp_x", "rentabilidad") == [("2025-12", 7.5), ("2026-06", 8.0)]


def test_riesgo_returns_nav_series(db):
    _add(db, "afp_x", VALOR_CUOTA_CODE, [("2026-04", 100.0), ("2026-05", 101.0), ("2026-06", 100.5)])
    trend = dimension_trend(db, "afp_x", "riesgo")
    assert [p for p, _ in trend] == ["2026-04", "2026-05", "2026-06"]


def test_missing_component_yields_empty(db):
    # solvencia sin activos_totales → no hay ratio computable.
    _add(db, "afp_x", "patrimonio", [("2025-12", 40.0)])
    assert dimension_trend(db, "afp_x", "solvencia") == []
