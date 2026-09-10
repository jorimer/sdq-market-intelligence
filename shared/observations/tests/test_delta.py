"""La línea base la elige la NATURALEZA de la serie, y lo que falta se declara.

Estos tests fijan el criterio del §5.2 del plan de entregables mensuales: no una tabla de
decisiones por indicador, sino una regla que lee lo que el emisor ya declaró.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.observations import service
from shared.observations.delta import (
    BASE_ANIO_ANTERIOR,
    BASE_ULTIMO_NIVEL,
    leer_delta,
)


@pytest.fixture()
def db():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    try:
        yield s
    finally:
        s.close()


def _punto(db, period, value, *, nature="flow", code="permisos", unit="conteo",
           sector="construction", **kw):
    service.upsert(db, sector_key=sector, series_code=code, period=period, value=value,
                   unit=unit, frequency="monthly", nature=nature, source="MIVHED", **kw)
    db.commit()


def _serie(delta, code="permisos"):
    return next(s for s in delta["series"] if s["serie"] == code)


# ── Un FLUJO se compara contra el mismo período del año anterior ─────────────────

def test_un_flujo_se_mide_contra_el_MISMO_MES_del_anio_anterior(db):
    """Medirlo contra el mes anterior publicaría el calendario como si fuera el ciclo.

    Julio contra junio en una serie con estación dice más sobre el verano que sobre el
    sector; julio contra julio aísla el movimiento real.
    """
    _punto(db, "2024-07", 100.0)
    _punto(db, "2025-06", 400.0)      # el mes anterior, deliberadamente muy distinto
    _punto(db, "2025-07", 130.0)

    s = _serie(leer_delta(db, sector_key="construction", period="2025-07"))
    assert s["linea_base"]["tipo"] == BASE_ANIO_ANTERIOR
    assert s["linea_base"]["periodo"] == "2024-07"
    assert s["movimiento"]["direccion"] == "sube"
    assert s["movimiento"]["variacion_pct"] == pytest.approx(30.0)


def test_un_STOCK_se_mide_contra_el_ultimo_nivel_publicado(db):
    """Un saldo no se acumula: se compara con lo que era."""
    _punto(db, "2024-07", 100.0, nature="stock", code="capacidad")
    _punto(db, "2025-06", 400.0, nature="stock", code="capacidad")
    _punto(db, "2025-07", 380.0, nature="stock", code="capacidad")

    s = _serie(leer_delta(db, sector_key="construction", period="2025-07"), "capacidad")
    assert s["linea_base"]["tipo"] == BASE_ULTIMO_NIVEL
    assert s["linea_base"]["periodo"] == "2025-06"
    assert s["movimiento"]["direccion"] == "baja"


@pytest.mark.parametrize("naturaleza", ["rate", "index"])
def test_una_TASA_se_mueve_en_PUNTOS_y_no_en_porcentaje(db, naturaleza):
    """De 4,23 % a 5,35 % subió 1,12 PUNTOS. «+26 %» es correcto y económicamente falso:
    se lee como que la tasa subió un cuarto de sí misma."""
    _punto(db, "2024-07", 4.23, nature=naturaleza, code="tasa", unit="%")
    _punto(db, "2025-07", 5.35, nature=naturaleza, code="tasa", unit="%")

    m = _serie(leer_delta(db, sector_key="construction", period="2025-07"), "tasa")["movimiento"]
    assert m["medida"] == "puntos"
    assert m["variacion_en_puntos"] == pytest.approx(1.12)
    assert m["variacion_pct"] is None, "una tasa no puede publicar variación porcentual"


def test_una_naturaleza_SIN_DECLARAR_no_se_computa(db):
    """Adivinar una sola transformación para todas es un error de categoría en el 37 % del
    catálogo. Se declara el motivo y la serie va a `sin_lectura`, no desaparece."""
    _punto(db, "2024-07", 100.0, nature="unknown", code="misteriosa")
    _punto(db, "2025-07", 130.0, nature="unknown", code="misteriosa")

    d = leer_delta(db, sector_key="construction", period="2025-07")
    assert all(s["serie"] != "misteriosa" for s in d["series"])
    motivo = next(s for s in d["sin_lectura"] if s["serie"] == "misteriosa")["motivo"]
    assert "adivinando" in motivo


# ── Lo que falta se DECLARA, nunca se rellena ────────────────────────────────────

def test_sin_linea_base_hay_valor_pero_NO_hay_delta(db):
    """Un cero o un promedio en lugar de la base convertiría un hueco en una afirmación."""
    _punto(db, "2025-07", 130.0)          # sin el 2024-07

    s = _serie(leer_delta(db, sector_key="construction", period="2025-07"))
    assert s["valor"] == 130.0
    assert "movimiento" not in s, "se publicó un movimiento sin línea base"
    assert "no_disponible" in s["linea_base"]


def test_una_linea_base_en_CERO_no_publica_porcentaje(db):
    """Dividir por cero da un infinito o una cifra de siete dígitos que se lee como una
    explosión del sector. El cambio absoluto sí es cierto y se sirve."""
    _punto(db, "2024-07", 0.0)
    _punto(db, "2025-07", 130.0)

    m = _serie(leer_delta(db, sector_key="construction", period="2025-07"))["movimiento"]
    assert m["variacion_pct"] is None
    assert m["variacion_absoluta"] == pytest.approx(130.0)
    assert "cero" in m["motivo_sin_pct"]


def test_la_serie_que_no_se_pudo_leer_se_LISTA_con_su_motivo(db):
    """Una lista que solo trae lo que salió bien se lee como que todo salió bien."""
    _punto(db, "2025-07", 130.0)
    _punto(db, "2024-07", 90.0, code="otra")     # sin observación del período pedido

    d = leer_delta(db, sector_key="construction", period="2025-07")
    assert {s["serie"] for s in d["sin_lectura"]} == {"otra"}


# ── La ventana móvil: el puente con el índice anual ──────────────────────────────

def _doce_meses(db, anio, valor):
    for m in range(1, 13):
        _punto(db, f"{anio}-{m:02d}", valor)


def test_un_flujo_trae_su_VENTANA_de_doce_meses_comparable_con_el_indice_anual(db):
    _doce_meses(db, 2024, 10.0)
    _doce_meses(db, 2025, 12.0)

    v = _serie(leer_delta(db, sector_key="construction", period="2025-12"))["ventana_movil_12m"]
    assert v["disponible"] is True
    assert v["valor"] == pytest.approx(144.0)          # 12 × 12
    assert v["linea_base"]["valor"] == pytest.approx(120.0)
    assert v["movimiento"]["variacion_pct"] == pytest.approx(20.0)


def test_la_ventana_EXIGE_los_doce_meses_y_declara_los_que_faltan(db):
    """Sumar los que haya y rotularlo «doce meses» publica una cifra que no es la que su
    nombre dice, y el lector no tiene cómo sospecharlo. Es la regla con la que banca cerró
    el ROA/ROE: sin los insumos se declara no disponible, no se cae al método viejo."""
    _doce_meses(db, 2025, 12.0)
    service.upsert(db, sector_key="construction", series_code="permisos", period="2025-04",
                   value=None, nature="flow", frequency="monthly")
    db.commit()

    v = _serie(leer_delta(db, sector_key="construction", period="2025-12"))["ventana_movil_12m"]
    assert v["disponible"] is False
    assert "2025-04" in v["meses_faltantes"]
    assert "valor" not in v, "se publicó una ventana incompleta con cara de ventana completa"


def test_un_STOCK_no_trae_ventana_movil(db):
    """Sumar doce saldos daría doce veces el mismo dinero. La ventana es de flujos."""
    _punto(db, "2024-07", 100.0, nature="stock", code="capacidad")
    _punto(db, "2025-07", 120.0, nature="stock", code="capacidad")
    s = _serie(leer_delta(db, sector_key="construction", period="2025-07"), "capacidad")
    assert "ventana_movil_12m" not in s


# ── Toda magnitud que se resta viaja con su medida ───────────────────────────────

def test_cada_fila_NOMBRA_su_unidad_su_base_y_su_emisor(db):
    """Una reconciliación que restaba una tasa trimestral de interanuales publicó la
    conversión de unidades como si fuera una brecha. El sujeto viaja con el número."""
    _punto(db, "2024-07", 100.0)
    _punto(db, "2025-07", 130.0)
    s = _serie(leer_delta(db, sector_key="construction", period="2025-07"))
    assert s["unidad"] == "conteo"
    assert s["emisor"] == "MIVHED"
    assert s["linea_base"]["tipo"] and s["linea_base"]["periodo"]
    assert s["movimiento"]["medida"] == "porcentaje"
