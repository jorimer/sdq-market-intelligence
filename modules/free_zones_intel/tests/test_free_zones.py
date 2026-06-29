"""Tests del conector CNZFE + scoring IZF + servicio (Eje Zonas Francas).

Parser contra CSV inline (estructura real CNZFE), scoring puro y el compute_and_persist
sobre DB en memoria. Nunca toca la red.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.cnzfe_client import parse_free_zone_vars
from modules.free_zones_intel.models.models import FreeZoneScore
from modules.free_zones_intel.scoring.attractiveness import compute_free_zone_index
from modules.free_zones_intel.service import compute_and_persist, get_latest


_CSV = (
    "﻿Año,Total parques aprobados,Total empresas operando,Total de empleos,"
    "Exportaciones (millones US$),Inversion total acumulada (millones US$),"
    "Gastos operativos locales (millones US$),Salarios operarios semanales (RD$),"
    "Salarios tecnicos semanales (RD$),Areas de naves ocupadas (pies cuadrados)\n"
    "2021,79,734,183232,7179.6,5903.1,1944.3,3646.83,6388.53,42452389.5\n"
    "2022,84,774,192461,7827.3,7160.9,1993.9,4222.61,7032.88,47488229.3\n"
    "2023,87,820,198034,7959.4,7496.2,2027.8,4628.53,7573.56,49171262.07\n"
    "2024,94,843,198552,8500.3,7735.7,2163.9,4879.08,8236.75,50679794.32\n"
)


def test_parse_free_zone_vars():
    v = parse_free_zone_vars(_CSV)
    assert set(v) == {2021, 2022, 2023, 2024}
    assert v[2024]["companies"] == 843
    assert v[2024]["exports_musd"] == pytest.approx(8500.3)
    assert v[2024]["jobs"] == 198552
    assert v[2021]["investment_musd"] == pytest.approx(5903.1)


def test_compute_index_full_coverage():
    idx = compute_free_zone_index(parse_free_zone_vars(_CSV))
    assert idx["coverage"] == pytest.approx(1.0, abs=1e-6)  # 4 dims con dato
    assert idx["fz_score"] is not None and idx["band"] is not None
    # exportaciones 7179.6→8500.3 (3y) ≈ 5.8% > 5% objetivo → score tope 100
    assert idx["dimensions"]["export_dynamism"]["score"] == 100.0
    # inversión 5903→7736 ≈ 9.4% > 5% → 100; empleo ~2.7%/3% → < 100
    assert idx["dimensions"]["investment_attraction"]["score"] == 100.0
    assert idx["dimensions"]["employment"]["score"] < 100.0
    assert idx["levels"]["companies"] == 843


def test_compute_index_partial_coverage_is_honest():
    # solo exportaciones con ≥2 puntos → cobertura 0.30, el resto ausente
    idx = compute_free_zone_index({2023: {"exports_musd": 100.0}, 2024: {"exports_musd": 110.0}})
    assert idx["dimensions"]["export_dynamism"]["score"] is None  # sin base a 3 años
    assert idx["coverage"] == 0.0  # ninguna dimensión con CAGR computable


def test_compute_index_no_data():
    idx = compute_free_zone_index({})
    assert idx["fz_score"] is None and idx["coverage"] == 0.0


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[FreeZoneScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_backfill_scores_persists_per_year(db):
    from modules.free_zones_intel.service import backfill_scores, get_scores
    v = parse_free_zone_vars(_CSV)  # 2021-2024
    r = backfill_scores(db, vars_by_year=v)
    # solo 2024 tiene base de CAGR a 3 años (2021) dentro del subconjunto → 1 año
    assert r["persisted_periods"] == ["2024"] and r["latest"] == "2024"
    assert {s.period for s in get_scores(db)} == {"2024"}
    backfill_scores(db, vars_by_year=v)  # idempotente
    assert len(get_scores(db)) == 1


def test_compute_and_persist_idempotent(db):
    v = parse_free_zone_vars(_CSV)
    r1 = compute_and_persist(db, vars_by_year=v)
    assert r1["period"] == "2024" and r1["coverage"] == pytest.approx(1.0, abs=1e-6)
    compute_and_persist(db, vars_by_year=v)  # re-run
    assert db.query(FreeZoneScore).count() == 1  # idempotente por período
    latest = get_latest(db)
    assert latest.period == "2024" and latest.fz_score is not None
    assert latest.companies == 843 and latest.exports_musd == pytest.approx(8500.3)
    assert latest.breakdown["dimensions"]["export_dynamism"]["score"] == 100.0
