"""Tests del conector INDOTEL + scoring IDT + servicio (Eje Telecom).

Parser contra un XLSX sintético (estructura real del boletín), scoring puro y el
compute_and_persist sobre DB en memoria. Nunca toca la red.
"""
import io

import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.indotel_client import POP_2022, parse_indicators
from modules.telecom_intel.models.models import TelecomScore
from modules.telecom_intel.scoring.penetration import compute_telecom_index
from modules.telecom_intel.service import compute_and_persist, get_latest


def _synthetic_xlsx() -> bytes:
    """Mini-boletín con la estructura real (Ind. Generales codes col3/total col5 + RESUMEN)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ind. Generales"
    ws.append(["MÓDULO", "MÉTRICA", "CÓDIGO", "INDICADOR", "TOTALES", "CLARO"])
    ws.append(["SUSC", "Líneas", "LTT.3er", "Líneas totales MARZO", 11265937, 6942645])
    ws.append(["SUSC", "Líneas", "LTT.1er", "Líneas totales ENERO", 11147096, 6852303])
    ws.append(["SUSC", "Susc", "TSI.3er", "Internet MARZO", 9584953, 5707540])
    ws.append(["SUSC", "Susc", "TSIBA", "Banda ancha", 8333835, 4660374])
    rs = wb.create_sheet("RESUMEN")
    rs.append(["REPORTE", None, None, None, None])
    rs.append([None, None, None, None, None])
    rs.append(["Indicadores", 2019, 2020, 2021, "Ene-Mar.22"])
    rs.append(["Ingresos Totales de Telecom", 86324672890.0, 86496226847.0, 92510993511.0, 24665470409.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_indicators_real_structure():
    ind = parse_indicators(_synthetic_xlsx())
    assert ind["lines_total"] == 11265937
    assert ind["internet_total"] == 9584953
    assert ind["broadband_total"] == 8333835
    assert ind["revenue_latest"] == 92510993511.0 and ind["revenue_prev"] == 86496226847.0


def test_compute_telecom_index_full_coverage():
    ind = {"lines_total": 11265937.0, "internet_total": 9584953.0,
           "broadband_total": 8333835.0, "revenue_latest": 92510993511.0,
           "revenue_prev": 86496226847.0}
    idx = compute_telecom_index(ind, POP_2022)
    assert idx["coverage"] == 1.0  # 3/3 dims con dato
    m = idx["metrics"]
    assert m["mobile_penetration"] == pytest.approx(104.7, abs=0.2)
    assert m["internet_penetration"] == pytest.approx(89.1, abs=0.2)
    assert m["broadband_share"] == pytest.approx(86.9, abs=0.2)
    assert m["revenue_growth"] == pytest.approx(6.95, abs=0.1)
    assert idx["band"] == "Fuerte"


def test_compute_telecom_index_no_data_honest():
    idx = compute_telecom_index({}, POP_2022)
    assert idx["telecom_score"] is None and idx["coverage"] == 0.0


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[TelecomScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_compute_and_persist_idempotent(db):
    ind = {"lines_total": 11265937.0, "internet_total": 9584953.0,
           "broadband_total": 8333835.0, "revenue_latest": 92510993511.0,
           "revenue_prev": 86496226847.0}
    r1 = compute_and_persist(db, indicators=dict(ind), period="2022-Q1")
    assert r1["period"] == "2022-Q1" and r1["coverage"] == 1.0
    compute_and_persist(db, indicators=dict(ind), period="2022-Q1")
    assert db.query(TelecomScore).count() == 1
    latest = get_latest(db)
    assert latest.period == "2022-Q1" and latest.telecom_score is not None
