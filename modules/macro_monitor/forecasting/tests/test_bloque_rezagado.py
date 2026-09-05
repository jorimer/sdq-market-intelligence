"""Qué variable recorta el FINAL del bloque — que es la que cuesta horizontes.

`armar` declaraba desde cuándo empieza cada variable y **no hasta dónde llega**. El inicio
cuesta muestra; el final cuesta HORIZONTES, y el bloque termina donde termina la variable más
atrasada.

**El defecto que esto destapó, medido en producción.** La serie de inflación del conector del
API tiene un hueco de seis meses (2025-11 → 2026-04) que se lleva el trimestre 2026-Q1
entero. Como el bloque es la intersección, el BVAR quedaba recortado en 2025-Q4 y sus dos
horizontes publicables caían sobre trimestres **ya cerrados**: el motor no podía emitir un
solo pronóstico, y nada fallaba — la operación terminaba «completado» con cero escritos.

La causa de fondo fue una suposición mía escrita como si fuera un hecho: que «la interanual
no es una columna del archivo del IPC». El archivo publica `variacion_porcentual_12_meses`,
que ES la interanual, con 511 meses desde 1984 y sin huecos. Las dos series son la misma
medición —0,0025 pp de diferencia media sobre 493 meses, que es el redondeo a dos decimales
del API—, así que corregirlo no mueve ningún número: destapa los seis meses que faltaban.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import bloque
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

INFLACION_CANONICA = "bcrd.xls.ipc_base_2019_2020.variacion_porcentual_12_meses"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _sembrar(db, *, hueco_en_inflacion=()):
    """Cinco variables mensuales/trimestrales que llegan al mismo trimestre, salvo el hueco."""
    meses = [f"{a}-{m:02d}" for a in range(2018, 2027) for m in range(1, 13)][:102]
    trimestres = [f"{a}-Q{q}" for a in range(2018, 2027) for q in (1, 2, 3, 4)][:34]
    for i, t in enumerate(trimestres):
        db.add(MacroSeries(series_code="bcrd.xls.pib_2018.serie_original_indice",
                           period=t, value=100.0 + i))
        db.add(MacroSeries(series_code="bcrd.xls.tasa_dolar_referencia_mc.promtrimestral.venta",
                           period=t, value=50.0 + i * 0.1))
    for i, m in enumerate(meses):
        if m not in hueco_en_inflacion:
            db.add(MacroSeries(series_code=INFLACION_CANONICA, period=m, value=4.0 + i * 0.01))
        db.add(MacroSeries(series_code="bcrd.xls.serie_tpm.tasa_de_politica_monetaria",
                           period=m, value=5.0))
        db.add(MacroSeries(series_code="bcrd.xls.taap_activad.promedio_ponderado",
                           period=m, value=12.0))
    db.commit()


# ── el código declarado ─────────────────────────────────────────────────────────────


def test_la_inflacion_sale_del_archivo_canonico_y_no_del_conector():
    """Guard estructural. La serie del conector tiene un hueco de seis meses que le cuesta
    un trimestre entero al bloque; volver a apuntarle es reintroducir el defecto."""
    var = next(v for v in bloque.BLOQUE if v.nombre == "inflacion")
    assert var.codigo == INFLACION_CANONICA
    assert "bcrd.inflacion" not in (var.codigo or ""), (
        "la inflación volvió a la serie del conector del API, que tiene el hueco")


def test_el_motivo_del_codigo_esta_escrito():
    """Elegir una serie concreta es una decisión de método y tiene que quedar a la vista."""
    var = next(v for v in bloque.BLOQUE if v.nombre == "inflacion")
    assert len(var.porque_este_codigo) > 200


# ── el sensor ───────────────────────────────────────────────────────────────────────


def test_el_bloque_declara_hasta_donde_llega_cada_variable(db):
    _sembrar(db)
    b = bloque.armar(db)
    assert b.trimestres
    assert set(b.fin_por_variable) == {v.nombre for v in bloque.BLOQUE}


def test_un_hueco_reciente_deja_a_la_variable_REZAGADA_y_con_nombre(db):
    """Sin esto, el bloque se acorta y nadie sabe de quién depende."""
    _sembrar(db, hueco_en_inflacion={"2026-01", "2026-02", "2026-03",
                                     "2026-04", "2026-05", "2026-06"})
    b = bloque.armar(db)
    assert "inflacion" in b.rezagadas, (
        "la variable con el hueco no aparece nombrada: el bloque se acorta en silencio")


def test_sin_huecos_la_inflacion_no_esta_rezagada(db):
    """El contraejemplo: si `rezagadas` marcara a todas, el test de arriba pasaría solo."""
    _sembrar(db)
    b = bloque.armar(db)
    assert "inflacion" not in b.rezagadas


def test_el_hueco_le_cuesta_trimestres_al_bloque(db):
    """La consecuencia medida, no la sospecha: el bloque con hueco es MÁS CORTO."""
    _sembrar(db)
    largo = len(bloque.armar(db).trimestres)
    db.query(MacroSeries).filter(
        MacroSeries.series_code == INFLACION_CANONICA,
        MacroSeries.period.in_(["2026-01", "2026-02", "2026-03"])).delete(
            synchronize_session=False)
    db.commit()
    corto = len(bloque.armar(db).trimestres)
    assert corto < largo, (
        "un hueco de un trimestre entero en una variable no acortó el bloque: la "
        "intersección no está haciendo su trabajo")
