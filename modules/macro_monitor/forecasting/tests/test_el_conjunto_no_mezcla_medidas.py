"""Dos pronósticos en MEDIDAS distintas no son un conjunto, aunque todo lo demás coincida.

El `backtest_id` es la clave del conjunto sobre el que se computa el error, y era
`{model_id}|{target_series}|+{h}T`. Le faltaba la medida — y eso no es teórico: el
2026-09-05, el bloque del BVAR cambió `pib_real` de variación TRIMESTRAL a INTERANUAL. Con la
clave vieja, el pronóstico emitido a las 11:19 (trimestral, punto 0,7373) y los que el mismo
modelo emite desde esa tarde (interanuales, ~5,5) caen en el mismo conjunto, y la sección de
desempeño promedia sus errores en un solo RMSE.

Es «solo se ordena lo comparable» sobre el eje del tiempo: un modelo que cambia de unidad
parte su propio track record en dos poblaciones, y promediarlas publica un número que no
mide nada. El QoQ del PIB dominicano promedia +1,13 % y el YoY +4,54 %: la mezcla no es un
matiz, es de otro tamaño.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import desempeno, ledger
from modules.macro_monitor.models.models import MacroSeries
from shared.data import medida_de_pronostico as med
from shared.database.base import Base

MODELO = "bvar_minnesota.5v.v1"
SERIE = "bcrd.xls.pib_2018.serie_original_indice"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _puntuada(db, *, medida, horizonte, as_of, punto, error):
    f = ledger.registrar(db, model_id=MODELO, target_series=SERIE, horizon=horizonte,
                         as_of=as_of, point=punto, h=2, measure=medida,
                         intervals=[[0.80, punto - 2, punto + 2]])
    f.status, f.realized = "scored", punto + error
    f.abs_error, f.sq_error = abs(error), error ** 2
    f.interval_hit_80 = True
    db.commit()
    return f


# ── El conjunto ─────────────────────────────────────────────────────────────────────


def test_dos_medidas_NO_son_el_mismo_conjunto(db):
    """El caso real: la fila trimestral del 2026-09-05 y las interanuales que vinieron
    después. Con la clave vieja el RMSE los promedia."""
    _puntuada(db, medida=med.DLOG_PCT, horizonte="2026-Q3", as_of="2026-09-05",
              punto=0.7373, error=0.5)
    _puntuada(db, medida=med.YOY_PCT, horizonte="2026-Q4", as_of="2026-09-30",
              punto=5.5672, error=4.0)

    trimestral = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 2,
                                                            med.DLOG_PCT))
    interanual = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 2,
                                                            med.YOY_PCT))
    assert trimestral["n_oos"] == 1 and interanual["n_oos"] == 1, (
        f"el conjunto mezcló medidas: trimestral n={trimestral['n_oos']}, "
        f"interanual n={interanual['n_oos']}")
    assert trimestral["rmse"] == pytest.approx(0.5)
    assert interanual["rmse"] == pytest.approx(4.0)


def test_la_medida_esta_EN_la_clave_del_conjunto(db):
    a = ledger.backtest_id(MODELO, SERIE, 2, med.DLOG_PCT)
    b = ledger.backtest_id(MODELO, SERIE, 2, med.YOY_PCT)
    assert a != b, f"la clave no distingue la medida: {a}"
    assert med.DLOG_PCT in a and med.YOY_PCT in b


def test_el_comodin_de_horizonte_sigue_acotado_a_UNA_medida(db):
    """`h=None` abarca todos los horizontes de un modelo — pero no todas sus unidades. Mezclar
    dificultades es una decisión declarada; mezclar unidades es un error."""
    _puntuada(db, medida=med.DLOG_PCT, horizonte="2026-Q3", as_of="2026-09-05",
              punto=0.7373, error=0.5)
    _puntuada(db, medida=med.YOY_PCT, horizonte="2026-Q4", as_of="2026-09-30",
              punto=5.5672, error=4.0)
    todos = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, None, med.DLOG_PCT))
    assert todos["n_oos"] == 1


# ── UN solo constructor ─────────────────────────────────────────────────────────────


def test_el_bvar_y_el_ledger_construyen_LA_MISMA_clave():
    """Había dos constructores. Una copia a mano de un serializador ya borró la tasa de 38
    entidades en este repo: si divergen, la meta apunta a un conjunto que no existe y la
    proyección nunca ancla."""
    import numpy as np

    from modules.macro_monitor.forecasting import bvar

    rng = np.random.default_rng(3)
    Y = np.cumsum(rng.normal(0, 1, (90, 3)), axis=0) * 0.1 + 4.0
    pr = bvar.proyectar_bloque(Y, ("pib_real", "b", "c"), "2026-Q1", pasos=4,
                               serie_objetivo=SERIE, medida=med.YOY_PCT)
    p = pr.pronosticos()[0]
    assert p.backtest_id == ledger.backtest_id(p.model_id, SERIE, p.h, med.YOY_PCT), (
        f"el BVAR arma «{p.backtest_id}» y el ledger arma "
        f"«{ledger.backtest_id(p.model_id, SERIE, p.h, med.YOY_PCT)}»")


# ── La sección de desempeño ─────────────────────────────────────────────────────────


def test_la_tabla_de_desempeno_publica_UN_RENGLON_POR_MEDIDA(db):
    """Un solo renglón con las dos mezcladas es el número que no mide nada, y es el que se
    vende."""
    db.add(MacroSeries(series_code=SERIE, period="2026-Q3", value=133.0))
    db.commit()
    _puntuada(db, medida=med.DLOG_PCT, horizonte="2026-Q3", as_of="2026-09-05",
              punto=0.7373, error=0.5)
    _puntuada(db, medida=med.YOY_PCT, horizonte="2026-Q4", as_of="2026-09-30",
              punto=5.5672, error=4.0)

    fs = desempeno.filas(db)
    assert len(fs) == 2, f"la tabla publicó {len(fs)} renglón(es) para dos medidas distintas"
    assert {f.rmse for f in fs} == {0.5, 4.0}
    # La tabla usa la forma DEFINICIONAL (`ETIQUETAS`), no la que acompaña a una cifra
    # (`COMO_SE_LEE`): acá la medida es el contenido de una columna, no una coletilla.
    texto = desempeno.seccion(db)
    for m in (med.DLOG_PCT, med.YOY_PCT):
        assert med.ETIQUETAS[m] in texto, (
            f"la tabla publica dos renglones del mismo modelo y el mismo horizonte sin decir "
            f"en qué medida está cada uno — se leen como una contradicción:\n{texto}")
