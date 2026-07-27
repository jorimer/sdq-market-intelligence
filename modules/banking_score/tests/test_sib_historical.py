"""Tests del loader histórico SIB (Cronología SB).

Cubre el parseo de los dos esquemas (situación con 4 niveles; resultados con 2
niveles + monto_desagregado), la normalización de casing de tipo_entidad, la
idempotencia (recargar reemplaza, no duplica) y la dedup de row_key intra-archivo.
"""
import io
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.banking_score.models.models import SibHistoricalLedger
from modules.banking_score.external import sib_historical_client as hist


# ── Fixtures de CSV en memoria (esquemas reales, recortados) ──────────

SITUACION_CSV = (
    "﻿FECHA,ANO,MES,PERIODICIDAD,ENTIDAD,NOMBRE_ENTIDAD,TIPO_ENTIDAD,SECTOR_ENTIDAD,"
    "TIPO_CAPITAL,DETALLE_NIVEL_1,DETALLE_NIVEL_2,DETALLE_NIVEL_3,DETALLE_NIVEL_4,MONTO\n"
    "2023-12-01,2023,12,Mensual,BPOPULAR,Banco Popular Dominicano,BANCOS MÚLTIPLES,Privado,"
    "Nacional,Activos,Total,Total,Total,755266000000.0\n"
    "2023-12-01,2023,12,Mensual,BPOPULAR,Banco Popular Dominicano,Bancos múltiples,Privado,"
    "Nacional,Pasivos,Depósitos del público,Depósitos del público,A la vista,512556564909.0\n"
)

RESULTADOS_CSV = (
    "﻿FECHA,ANO,MES,PERIODICIDAD,ENTIDAD,NOMBRE_ENTIDAD,TIPO_ENTIDAD,SECTOR_ENTIDAD,"
    "TIPO_CAPITAL,DETALLE_NIVEL_1,DETALLE_NIVEL_2,MONTO,MONTO_DESAGREGADO\n"
    "2023-12-01,2023,12,Mensual,BPOPULAR,Banco Popular Dominicano,Bancos Múltiples,Privado,"
    "Nacional,Resultado del ejercicio,Resultado del ejercicio,22893696065.0,22893696065.0\n"
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SibHistoricalLedger.__table__])
    return sessionmaker(bind=engine)()


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ── Parseo ────────────────────────────────────────────────────────────

def test_parse_situacion_schema():
    rows = list(hist.parse_rows(io.StringIO(SITUACION_CSV), "situacion", "f.csv"))
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["fecha"] == date(2023, 12, 1)
    assert r0["ano"] == 2023 and r0["mes"] == 12
    assert r0["entidad_code"] == "BPOPULAR"
    assert r0["nivel_1"] == "Activos" and r0["nivel_4"] == "Total"
    assert float(r0["monto"]) == 755266000000.0
    assert r0["monto_desagregado"] is None  # situación no trae la columna


def test_parse_resultados_schema():
    rows = list(hist.parse_rows(io.StringIO(RESULTADOS_CSV), "resultados", "r.csv"))
    assert len(rows) == 1
    r = rows[0]
    assert r["nivel_1"] == "Resultado del ejercicio"
    assert r["nivel_3"] is None and r["nivel_4"] is None  # resultados: solo 2 niveles
    assert float(r["monto_desagregado"]) == 22893696065.0


def test_tipo_entidad_casing_normalised():
    """'BANCOS MÚLTIPLES' y 'Bancos múltiples' deben colapsar al mismo valor."""
    sit = list(hist.parse_rows(io.StringIO(SITUACION_CSV), "situacion", "f.csv"))
    tipos = {r["tipo_entidad"] for r in sit}
    assert tipos == {"Bancos Múltiples"}  # acento preservado, casing unificado


def test_row_key_stable_and_distinct():
    rows = list(hist.parse_rows(io.StringIO(SITUACION_CSV), "situacion", "f.csv"))
    assert rows[0]["row_key"] != rows[1]["row_key"]
    # determinista: reparsear da la misma llave
    again = list(hist.parse_rows(io.StringIO(SITUACION_CSV), "situacion", "f.csv"))
    assert rows[0]["row_key"] == again[0]["row_key"]


# ── Carga e idempotencia ──────────────────────────────────────────────

def test_load_file_inserts(db, tmp_path):
    rec = {"estado": "situacion", "periods": "2017_2026", "url": "x"}
    path = _write(tmp_path, "s.csv", SITUACION_CSV)
    n = hist.load_file(db, rec, local_path=path)
    assert n == 2
    assert db.query(SibHistoricalLedger).count() == 2
    row = db.query(SibHistoricalLedger).filter_by(nivel_1="Activos").one()
    assert row.source_file == "estadosituacion_2017_2026.csv"
    assert row.snapshot_date == hist.SNAPSHOT_DATE


def test_reload_is_idempotent(db, tmp_path):
    """Recargar el mismo archivo reemplaza sus filas — no duplica."""
    rec = {"estado": "situacion", "periods": "2017_2026", "url": "x"}
    path = _write(tmp_path, "s.csv", SITUACION_CSV)
    hist.load_file(db, rec, local_path=path)
    hist.load_file(db, rec, local_path=path)  # segunda corrida
    assert db.query(SibHistoricalLedger).count() == 2  # no 4


def test_intra_file_duplicate_key_deduped(db, tmp_path):
    """Dos filas con la misma llave natural no abortan el batch (se dedup)."""
    dup = SITUACION_CSV + (
        "2023-12-01,2023,12,Mensual,BPOPULAR,Banco Popular Dominicano,Bancos Múltiples,Privado,"
        "Nacional,Activos,Total,Total,Total,999.0\n"  # misma llave que la fila 1
    )
    path = _write(tmp_path, "s.csv", dup)
    rec = {"estado": "situacion", "periods": "2017_2026", "url": "x"}
    n = hist.load_file(db, rec, local_path=path)
    assert n == 2  # la duplicada se descartó
