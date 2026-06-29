"""Tests del conector ONE llegadas + scoring ITT + servicio (Eje Turismo).

Parser contra CSV inline (estructura real ONE), scoring puro y el compute_and_persist
sobre DB en memoria. Nunca toca la red.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.tourism_arrivals_client import parse_arrivals
from modules.tourism_intel.models.models import TourismScore
from modules.tourism_intel.scoring.traction import compute_tourism_index
from modules.tourism_intel.service import compute_and_persist, get_latest


# Estructura real: categoría · sexo · total · año. Mezcla filas resumen (no residentes)
# y filas de región (América del norte/sur, Europa). Las regiones suman a los extranjeros.
def _row(cat, sexo, total, year):
    return f"{cat},{sexo},{total},{year}"


def _build_csv():
    header = ("Llegada de Pasajeros por Nacionalidad,Sexo,"
              "Total de Llegada de Pasajero por Nacionalidad,Año")
    rows = [header]
    spec = {
        2019: {"dom": 1000, "na": 3000, "eu": 1200, "as": 800},
        2022: {"dom": 1300, "na": 3500, "eu": 1200, "as": 800},
        2023: {"dom": 1400, "na": 3800, "eu": 1300, "as": 900},
        2024: {"dom": 1500, "na": 4100, "eu": 1400, "as": 1000},
        2025: {"dom": 1600, "na": 4400, "eu": 1500, "as": 1100},
    }
    for y, v in spec.items():
        foreign = v["na"] + v["eu"] + v["as"]
        # split 2025 diaspora across sex to exercise sex-summing
        if y == 2025:
            rows.append(_row("Dominicanos no residentes", "Femenino", v["dom"] // 2, y))
            rows.append(_row("Dominicanos no residentes", "Masculino", v["dom"] - v["dom"] // 2, y))
        else:
            rows.append(_row("Dominicanos no residentes", "Total", v["dom"], y))
        rows.append(_row("Extranjeros no residentes", "Total", foreign, y))
        rows.append(_row("América del norte", "Total", v["na"], y))
        rows.append(_row("Europa", "Total", v["eu"], y))
        rows.append(_row("América del sur", "Total", v["as"], y))
        # a country row that must NOT be summed into regions (overlaps Norteamérica)
        rows.append(_row("Estados Unidos", "Total", v["na"] - 500, y))
    return "\n".join(rows) + "\n"


_CSV = _build_csv()


def test_parse_arrivals():
    a = parse_arrivals(_CSV)
    assert set(a) == {2019, 2022, 2023, 2024, 2025}
    # 2025: foreign = 4400+1500+1100 = 7000; nonresident = foreign + 1600
    assert a[2025]["foreign"] == 7000
    assert a[2025]["nonresident"] == 8600
    # regions are mutually exclusive — country row "Estados Unidos" NOT added in
    assert set(a[2025]["regions"]) == {"América del Norte", "Europa", "América del Sur"}
    assert sum(a[2025]["regions"].values()) == a[2025]["foreign"]


def test_compute_index_full_coverage():
    idx = compute_tourism_index(parse_arrivals(_CSV))
    assert idx["coverage"] == pytest.approx(1.0, abs=1e-6)  # 4 dims con dato
    assert idx["itt_score"] is not None and idx["band"] == "Fuerte"
    # demanda creciendo > 5%/año objetivo → score tope 100
    assert idx["dimensions"]["total_demand"]["score"] == 100.0
    assert idx["dimensions"]["foreign_demand"]["score"] == 100.0
    # recuperación: 8600 (2025) vs pico pre-pandemia 2019 (6000) = 143% → 100
    assert idx["recovery"]["peak_year"] == 2019
    assert idx["recovery"]["score"] == 100.0
    # diversificación: concentrada pero repartida → entre 0 y 100
    div = idx["dimensions"]["diversification"]["score"]
    assert 0.0 < div < 100.0
    assert idx["levels"]["nonresident"] == 8600


def test_compute_index_partial_coverage_is_honest():
    # solo no residentes con 2 puntos post-2020, sin base a 3 años, sin regiones
    idx = compute_tourism_index({
        2024: {"nonresident": 100.0, "foreign": 0.0, "regions": {}},
        2025: {"nonresident": 110.0, "foreign": 0.0, "regions": {}},
    })
    assert idx["dimensions"]["total_demand"]["score"] is None  # sin base a 3 años
    assert idx["dimensions"]["recovery"]["score"] is None       # sin año pre-2020
    assert idx["dimensions"]["diversification"]["score"] is None  # sin regiones
    assert idx["coverage"] == 0.0


def test_compute_index_no_data():
    idx = compute_tourism_index({})
    assert idx["itt_score"] is None and idx["coverage"] == 0.0


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[TourismScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_compute_and_persist_idempotent(db):
    a = parse_arrivals(_CSV)
    r1 = compute_and_persist(db, arrivals_by_year=a)
    assert r1["period"] == "2025" and r1["coverage"] == pytest.approx(1.0, abs=1e-6)
    compute_and_persist(db, arrivals_by_year=a)  # re-run
    assert db.query(TourismScore).count() == 1  # idempotente por período
    latest = get_latest(db)
    assert latest.period == "2025" and latest.itt_score is not None
    assert latest.nonresident == 8600 and latest.foreign == 7000
    assert latest.breakdown["dimensions"]["total_demand"]["score"] == 100.0
