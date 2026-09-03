"""La cadencia se persiste en la ingesta, en un solo idioma, sin cambiarle el valor a nadie.

Tres cosas distintas se prueban acá:

1. **Que se escriba.** `mm_series.frequency` estaba NULL en las 509 filas de dev: la columna
   existía y el ingestor no la poblaba, así que cada lector la derivaba por su cuenta.
2. **Que no cambie el contrato.** `/series` de la Data API ya devuelve `frequency` —hoy
   derivándola al leer— y PMS la consume. Pasar de derivada-al-leer a persistida NO puede
   cambiar el valor que el cliente recibe. Es la prueba que decidió el vocabulario.
3. **Que la discrepancia se DECLARE.** Una serie que el registro declara trimestral cuyos
   períodos salen mensuales tiene el eje temporal mal leído. Eso no se arregla eligiendo uno
   de los dos valores: se declara, porque la serie entera es sospechosa.
"""
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.macro_monitor.service import (
    _discrepancias_de_cadencia, _infer_frequency, _upsert_records,
)
from shared.data.series_cadence import CADENCIAS
from shared.database.base import Base


@dataclass
class _Rec:
    series: str
    period: str
    value: Optional[float]
    unit: Optional[str] = None
    lineage: Any = None


@dataclass
class _Entrada:
    key: str
    frequency: str
    excel_series_suffix: Optional[str]


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


def _freq(db, code, period):
    return db.query(MacroSeries).filter_by(series_code=code, period=period).one().frequency


# ── 1 · se escribe, y en el vocabulario de la columna ────────────────────────────

@pytest.mark.parametrize("period,esperada", [
    ("2026", "annual"), ("2026-Q1", "quarterly"), ("2026-07", "monthly"),
])
def test_la_ingesta_puebla_la_cadencia_desde_el_periodo(db, period, esperada):
    _upsert_records(db, [_Rec("s.demo", period, 1.0)])
    assert _freq(db, "s.demo", period) == esperada


def test_ninguna_fila_queda_sin_cadencia_ni_en_espanol(db):
    _upsert_records(db, [_Rec("s.a", "2026", 1.0), _Rec("s.b", "2026-Q2", 2.0),
                         _Rec("s.c", "2026-03", 3.0)])
    escritas = {r.frequency for r in db.query(MacroSeries).all()}
    assert None not in escritas
    assert escritas <= set(CADENCIAS), f"fuera del vocabulario de la columna: {escritas}"


def test_una_segunda_corrida_no_cambia_la_cadencia(db):
    """El guard de nulos frena el VALOR, no la cadencia: re-ingerir tiene que ser idempotente
    en las dos columnas."""
    _upsert_records(db, [_Rec("s.demo", "2026-Q1", 1.0)])
    _upsert_records(db, [_Rec("s.demo", "2026-Q1", None)])
    assert _freq(db, "s.demo", "2026-Q1") == "quarterly"


# ── 2 · el contrato de la Data API no se mueve ───────────────────────────────────

@pytest.mark.parametrize("periodos", [
    ["2007-Q1", "2007-Q2", "2026-Q1"],      # pib_real
    ["1984-01", "2000-06", "2026-07"],      # ipc_general
    ["2019", "2020", "2021"],               # una serie anual
])
def test_lo_persistido_coincide_con_lo_que_la_api_derivaba(db, periodos):
    """Lo que `/series` devolvía derivando al leer, y lo que ahora sale persistido, tienen
    que ser el MISMO valor. Si difieren, el cambio le mueve el campo a PMS."""
    _upsert_records(db, [_Rec("s.contrato", p, 1.0) for p in periodos])
    persistidas = {r.frequency for r in db.query(MacroSeries).all()}
    assert len(persistidas) == 1
    assert persistidas.pop() == _infer_frequency(periodos)


# ── 3 · la discrepancia se declara ───────────────────────────────────────────────

def test_una_cadencia_declarada_que_contradice_los_periodos_se_declara():
    entradas = [_Entrada("pib_real", "trimestral", "serie_original_indice")]
    records = [_Rec("bcrd.xls.pib_2018.serie_original_indice", p, 1.0)
               for p in ("2026-01", "2026-02")]          # mensuales, no trimestrales
    salida = _discrepancias_de_cadencia(entradas, records)
    assert len(salida) == 1
    assert "pib_real" in salida[0] and "quarterly" in salida[0] and "monthly" in salida[0]


def test_sin_discrepancia_no_se_declara_nada():
    entradas = [_Entrada("pib_real", "trimestral", "serie_original_indice")]
    records = [_Rec("bcrd.xls.pib_2018.serie_original_indice", p, 1.0)
               for p in ("2026-Q1", "2026-Q2")]
    assert _discrepancias_de_cadencia(entradas, records) == []


def test_una_entrada_sin_puente_no_se_puede_verificar():
    """17 de las 50 entradas no tienen `excel_series_suffix`: no apuntan a ninguna serie y
    no hay contra qué comparar. Que no se verifiquen es un hecho declarado, no un olvido —
    y sobre todo NO puede producir un falso positivo."""
    entradas = [_Entrada("inflacion_interanual", "mensual", None)]
    records = [_Rec("bcrd.xls.ipc_base_2019_2020.indice", "2026-Q1", 1.0)]
    assert _discrepancias_de_cadencia(entradas, records) == []


# ── La frontera de escritura veta las DOS coordenadas ────────────────────────────

def test_un_codigo_desempatado_por_columna_no_se_persiste(db):
    _upsert_records(db, [_Rec("bcrd.xls.f.tasa_de_inflacion_c5", "2026-01", 1.0)])
    assert db.query(MacroSeries).count() == 0


def test_un_codigo_desempatado_por_FILA_tampoco(db):
    """`agropecuario_r46` dice en qué FILA estaba, no si mide el nivel, la tasa de
    crecimiento o la incidencia. Es la misma pérdida de sujeto que `_c<n>`, por el otro eje:
    el cuadro del PIB por origen repite cada sector en tres bloques."""
    _upsert_records(db, [_Rec("bcrd.xls.pib_origen_2018.pibk_trim.agropecuario_r46",
                              "2026-Q1", 1.0)])
    assert db.query(MacroSeries).count() == 0


def test_un_codigo_con_sujeto_si_se_persiste(db):
    """El guard veta la COORDENADA, no cualquier número al final: una serie legítimamente
    numerada —una base, un manual, un quintil— tiene que pasar."""
    for code in ("bcrd.xls.pib_origen_2018.pibk_trim.agropecuario",
                 "bcrd.xls.ipc_quintiles_base_2019_2020.quintil_5",
                 "bcrd.xls.bpagos_6.1_cuenta_corriente"):
        _upsert_records(db, [_Rec(code, "2026-Q1", 1.0)])
    assert db.query(MacroSeries).count() == 3
