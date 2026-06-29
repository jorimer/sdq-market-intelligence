"""Tests de conectores (SIE capacidad/reclamaciones + ONE generación) + scoring IRSE
+ servicio (Eje Energía).

Parsers contra CSV inline (estructura real, Latin-1/';'), scoring puro (incl. la
dimensión de transición renovable) y el compute_and_persist sobre DB en memoria.
Nunca toca la red.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.sie_client import parse_claims, parse_installed_capacity
from shared.data.generation_client import (
    parse_generation_shares,
    renewable_share_by_year,
)
from modules.energy_intel.models.models import EnergyScore
from modules.energy_intel.scoring.resilience import (
    capacity_metrics,
    compute_energy_index,
    service_metrics,
    transition_metrics,
)
from modules.energy_intel.service import compute_and_persist, get_latest


# ── Parsers del client (estructura real) ──

_CAP_CSV = (
    "DIRECCCION MERCADO ELECTRICO MAYORISTA ,,,,\n"
    "MOVIMIENTO DE GENERACION ANUAL,,,,\n"
    "ENTRADA (MW),SALIDA (MW),MOVIMIENTO,A?O,POTENCIA (MW)\n"
    '"1,947.76",0.00,previo,1998,"1,947.76"\n'
    "100.00,0.00,altas,2024,\"6,500.00\"\n"
    "201.11,0.00,altas,2026,\"7,054.05\"\n"
    ",,,,\n"
)

_CLAIMS_CSV = (
    "A?o,Mes, Recibidas , Procedentes , Improcedentes , Total Decisiones , En Proceso \n"
    '2025,Enero," 4,000 "," 1,000 "," 2,000 "," 3,000 "," 30,000 "\n'
    '2025,Febrero," 5,000 "," 1,500 "," 2,500 "," 4,000 "," 38,000 "\n'
)


def test_parse_installed_capacity():
    cap = parse_installed_capacity(_CAP_CSV)
    assert cap[1998] == pytest.approx(1947.76)
    assert cap[2026] == pytest.approx(7054.05)
    assert max(cap) == 2026


def test_parse_claims():
    rows = parse_claims(_CLAIMS_CSV)
    assert len(rows) == 2
    assert rows[0]["period"] == "2025-01" and rows[0]["recibidas"] == 4000.0
    assert rows[-1]["en_proceso"] == 38000.0


# Generación por tecnología (ONE) — ';'-separado, columna Porcentaje robusta. Incluye
# un año corrupto (cuotas que no suman ~100, como el Solar inflado real de 2025) que
# debe descartarse.
_GEN_CSV = (
    "Tipo de Generación de Energia ; Total de Energia;Porcentaje;Año;\n"
    "Ciclo combinado GWh;7000;35;2019;\n"
    "Éolica GWh;600;3;2019;\n"
    "Turbinas a gas GWh;400;2;2019;\n"
    "Turbinas a vapor GWh;5600;28;2019;\n"
    "Motores diesel GWh;4200;21;2019;\n"
    "Hidráulica GWh;1200;6;2019;\n"
    "Solar GWh;1000;5;2019;\n"
    "Ciclo combinado GWh;6000;30;2024;\n"
    "Éolica GWh;1000;5;2024;\n"
    "Turbinas a gas GWh;200;1;2024;\n"
    "Turbinas a vapor GWh;5000;25;2024;\n"
    "Motores diesel GWh;4600;23;2024;\n"
    "Hidráulica GWh;1200;6;2024;\n"
    "Solar GWh;2000;10;2024;\n"
    # 2025 corrupto: Solar inflado, cuotas suman 60 ≠ 100 → se descarta
    "Solar GWh;23638;9;2025;\n"
    "Ciclo combinado GWh;6964;26;2025;\n"
    "Turbinas a vapor GWh;7750;25;2025;\n"
)


def test_parse_generation_drops_corrupt_year():
    shares = parse_generation_shares(_GEN_CSV)
    assert set(shares) == {2019, 2024}  # 2025 descartado (suma ≠ 100)
    assert sum(shares[2024].values()) == pytest.approx(100, abs=1)


def test_renewable_share_eolica_hidraulica_solar():
    ren = renewable_share_by_year(parse_generation_shares(_GEN_CSV))
    assert ren[2019] == pytest.approx(14.0)   # 3 + 6 + 5
    assert ren[2024] == pytest.approx(21.0)   # 5 + 6 + 10


# ── Scoring puro ──

def test_capacity_metrics_growth():
    cap = {2022: 5000.0, 2023: 5500.0, 2024: 6000.0, 2025: 6600.0}
    m = capacity_metrics(cap)
    assert m["capacity_mw"] == 6600.0
    assert m["cagr_3y"] is not None and m["score"] is not None
    # CAGR (6600/5000)^(1/3)-1 ≈ 9.7% > 4% target → score tope 100
    assert m["score"] == 100.0


def test_service_metrics_backlog_penalizes():
    claims = [{"period": f"2025-{m:02d}", "recibidas": 4000.0, "en_proceso": 32000.0}
              for m in range(1, 13)]
    m = service_metrics(claims)
    # backlog 32000/4000 = 8 meses → score bajo
    assert m["backlog_months"] == pytest.approx(8.0)
    assert m["score"] < 30


def test_transition_metrics_vs_national_target():
    # penetración 21 % contra meta 25 % (Ley 57-07) → score 84; delta vs 5 años antes
    m = transition_metrics({2019: 14.0, 2024: 21.0})
    assert m["renewable_share"] == 21.0 and m["year"] == 2024
    assert m["delta_5y"] == pytest.approx(7.0)
    assert m["score"] == pytest.approx(84.0)


def test_transition_metrics_no_data_is_gap():
    assert transition_metrics(None)["score"] is None
    assert transition_metrics({})["score"] is None


def test_compute_energy_index_partial_coverage():
    cap = {2022: 5000.0, 2025: 6600.0}
    claims = [{"period": "2025-12", "recibidas": 4000.0, "en_proceso": 8000.0}]
    idx = compute_energy_index(cap, claims)
    # sin generación: 2 de 3 dims → cobertura 0.65 (capacidad 0.35 + servicio 0.30)
    assert idx["coverage"] == pytest.approx(0.65, abs=1e-6)
    assert idx["dimensions"]["energy_transition"]["score"] is None  # brecha
    assert idx["energy_score"] is not None and idx["band"] is not None


def test_compute_energy_index_full_coverage_with_transition():
    cap = {2022: 5000.0, 2025: 6600.0}
    claims = [{"period": "2025-12", "recibidas": 4000.0, "en_proceso": 8000.0}]
    idx = compute_energy_index(cap, claims, {2019: 14.0, 2024: 21.0})
    # las 3 dims con dato → cobertura plena
    assert idx["coverage"] == pytest.approx(1.0, abs=1e-6)
    t = idx["dimensions"]["energy_transition"]
    assert t["provenance"] == "real" and t["score"] == pytest.approx(84.0)
    assert idx["transition"]["renewable_share"] == 21.0


def test_compute_energy_index_no_data_is_honest():
    idx = compute_energy_index({}, [])
    assert idx["energy_score"] is None and idx["coverage"] == 0.0


# ── Servicio (DB en memoria) ──

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[EnergyScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_compute_and_persist_idempotent(db):
    cap = {2022: 5000.0, 2023: 5500.0, 2024: 6000.0, 2025: 6600.0}
    claims = [{"period": "2025-12", "recibidas": 4000.0, "en_proceso": 8000.0}]
    r1 = compute_and_persist(db, capacity_by_year=cap, claims=claims)
    assert r1["period"] == "2025" and r1["coverage"] == pytest.approx(0.65, abs=1e-6)
    compute_and_persist(db, capacity_by_year=cap, claims=claims)  # re-run
    assert db.query(EnergyScore).count() == 1  # idempotente por período
    latest = get_latest(db)
    assert latest.period == "2025" and latest.energy_score is not None


def test_compute_and_persist_with_transition(db):
    cap = {2022: 5000.0, 2023: 5500.0, 2024: 6000.0, 2025: 6600.0}
    claims = [{"period": "2025-12", "recibidas": 4000.0, "en_proceso": 8000.0}]
    r = compute_and_persist(db, capacity_by_year=cap, claims=claims,
                            renewable_share_by_year={2019: 14.0, 2024: 21.0})
    assert r["coverage"] == pytest.approx(1.0, abs=1e-6)  # 3 dims con dato
    latest = get_latest(db)
    assert latest.transition_score == pytest.approx(84.0)
    assert latest.breakdown["transition"]["renewable_share"] == 21.0
