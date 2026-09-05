"""La clave del track record es el horizonte RELATIVO, no el trimestre calendario.

**El defecto que este archivo existe para impedir.** El conjunto de pronósticos sobre el que
se computa el error estaba identificado por el trimestre CALENDARIO. Pero un trimestre
calendario se pronostica **una sola vez** a cada distancia: el conjunto de «2025-Q4 a un
trimestre vista» tiene exactamente UNA observación. Medido: doce trimestres emitidos y
puntuados —tres años de operación perfecta— daban `n_oos = 1`, y el gate exige doce.

O sea: **la proyección no habría anclado nunca**. Y el modo de falla es el peor de todos, no
una excepción sino un mensaje razonable: «1 observación fuera de muestra, hacen falta al
menos 12» — exactamente lo que dice el estado honesto del día uno. Un guard que siempre
responde que no y parece que todavía no.

La pregunta que el track record responde es «¿qué tan bien pronosticamos a UN trimestre
vista?». Ésa se acumula a lo largo de los trimestres. «¿Qué tan bien pronosticamos 2025-Q4?»
es una muestra de uno.

El test central es de PASO DEL TIEMPO: simula años de operación y exige que el producto
llegue a anclar. Ningún test de una sola emisión podía verlo.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import ledger as led
from shared.data import medida_de_pronostico as med
from modules.macro_monitor.forecasting import procedencia as proc
from modules.macro_monitor.models.models import MacroSeries  # noqa: F401
from shared.database.base import Base
from shared.registry.projection import MIN_OOS

# `SERIE` es el `series_code` OBSERVABLE, no el nombre de la variable en el bloque: decía
# `"pib_real"`, y una fila con ese objetivo no se puede puntuar contra nada porque no existe
# ninguna serie que se llame así.
MODELO, SERIE = "bvar.v1", "bcrd.xls.pib_2018.serie_original_indice"
INTERVALOS = [[0.80, 2.0, 4.0], [0.90, 1.5, 4.5]]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


_TRIMESTRES = [(a, q) for a in (2022, 2023, 2024, 2025) for q in (1, 2, 3, 4)]


def _corte(i: int, h: int) -> str:
    """El corte de información, *h* trimestres ANTES del objetivo. Eso ES un horizonte h."""
    a, q = _TRIMESTRES[i - h]
    return f"{a}-{(q - 1) * 3 + 1:02d}-15"


def _operar(db, *, pasos=(1, 2), desde=2):
    """Simula el paso del tiempo: cada trimestre se pronostica a cada distancia y, al
    cerrar, se puntúa."""
    for i, (a, q) in enumerate(_TRIMESTRES):
        if i < desde:
            continue
        for h in pasos:
            f = led.registrar(db, model_id=MODELO, target_series=SERIE,
                              horizon=f"{a}-Q{q}", as_of=_corte(i, h), point=3.0,
                              intervals=INTERVALOS, h=h,
                              measure=med.DLOG_PCT)
            f.status, f.realized, f.abs_error, f.sq_error = "scored", 3.2, 0.2, 0.04
            f.interval_hit_80, f.interval_hit_90 = True, True
    db.commit()


# ── el test que habría cazado el defecto ────────────────────────────────────────────


def test_anos_de_operacion_llegan_a_anclar(db):
    """El invariante del producto entero: con suficientes trimestres cerrados, la proyección
    ANCLA. Si esto falla, el eje prospectivo es decorativo."""
    _operar(db)
    tr = led.track_record(db, led.backtest_id(MODELO, SERIE, 1))
    assert tr["n_oos"] >= MIN_OOS, (
        f"tras años de operación el conjunto de +1T tiene {tr['n_oos']} observaciones y el "
        f"gate exige {MIN_OOS}: la proyección no ancla NUNCA, y el motivo que ve el lector "
        "es indistinguible del estado honesto del día uno")


def test_cada_distancia_es_su_propio_conjunto(db):
    """Mezclar +1T con +2T promediaría errores de dificultad distinta y la calibración
    reportada no sería la de ninguno de los dos."""
    _operar(db)
    uno = led.track_record(db, led.backtest_id(MODELO, SERIE, 1))
    dos = led.track_record(db, led.backtest_id(MODELO, SERIE, 2))
    juntos = led.track_record(db, led.backtest_id(MODELO, SERIE, None))
    assert uno["n_oos"] == dos["n_oos"]
    assert juntos["n_oos"] == uno["n_oos"] + dos["n_oos"]


def test_el_conjunto_de_un_trimestre_calendario_seria_de_uno(db):
    """El contraejemplo, escrito: es POR ESTO que la clave no puede ser el calendario."""
    _operar(db, pasos=(1,))
    from modules.macro_monitor.forecasting.models import ForecastLog
    de_un_trimestre = (db.query(ForecastLog)
                       .filter(ForecastLog.horizon == "2025-Q4",
                               ForecastLog.h == 1).count())
    assert de_un_trimestre == 1, (
        "un trimestre calendario se pronostica UNA vez a cada distancia; por eso un conjunto "
        "identificado por el calendario nunca puede sostener un error")


def test_el_horizonte_cero_del_nowcast_no_cae_al_comodin():
    """`h = 0` es falsy: con `if h` en vez de `if h is not None`, el nowcast del trimestre en
    curso se habría mezclado con TODOS los horizontes."""
    assert led.backtest_id(MODELO, SERIE, 0).endswith("|+0T")
    assert led.backtest_id(MODELO, SERIE, None).endswith("|*")


# ── las filas viejas no se inventan un horizonte ────────────────────────────────────


def test_una_fila_sin_h_queda_fuera_del_conjunto(db):
    """Anteriores a la migración. Adivinarles el horizonte sería fabricar track record, que
    es lo único que este ledger existe para impedir."""
    _operar(db, pasos=(1,))
    antes = led.track_record(db, led.backtest_id(MODELO, SERIE, 1))["n_oos"]
    f = led.registrar(db, model_id=MODELO, target_series=SERIE, horizon="2021-Q1",
                      as_of="2020-10-15", point=9.9, intervals=INTERVALOS,
                      measure=med.DLOG_PCT)  # sin h
    f.status, f.abs_error, f.sq_error = "scored", 5.0, 25.0
    db.commit()
    despues = led.track_record(db, led.backtest_id(MODELO, SERIE, 1))["n_oos"]
    assert despues == antes
    assert led.track_record(db, led.backtest_id(MODELO, SERIE, None))["n_oos"] == antes


# ── el solapamiento, que recién ahora significa algo ────────────────────────────────


def test_una_sola_emision_por_trimestre_no_solapa(db):
    _operar(db, pasos=(1,))
    assert led.track_record(db, led.backtest_id(MODELO, SERIE, 1))["overlapping"] is False


def test_re_emitir_el_mismo_trimestre_si_solapa(db):
    """La emisión se dispara en cascada tras cada ingesta canónica, que es MENSUAL: el mismo
    trimestre puede pronosticarse a la misma distancia desde cortes distintos. Son
    observaciones que comparten información y el conteo lo DECLARA."""
    _operar(db, pasos=(1,))
    f = led.registrar(db, model_id=MODELO, target_series=SERIE, horizon="2025-Q4",
                      as_of="2025-08-15", point=3.1, intervals=INTERVALOS, h=1,
                      measure=med.DLOG_PCT)
    f.status, f.abs_error, f.sq_error = "scored", 0.1, 0.01
    db.commit()
    assert led.track_record(db, led.backtest_id(MODELO, SERIE, 1))["overlapping"] is True


# ── la meta que se sirve al lector ──────────────────────────────────────────────────


def test_la_meta_apunta_al_conjunto_relativo_y_conserva_el_calendario(db):
    """Las dos cosas a la vez: el `backtest_id` es relativo —para que el error signifique
    algo— y el `horizon` que el lector ve es el trimestre concreto que se proyecta."""
    _operar(db)
    fila = led.registrar(db, model_id=MODELO, target_series=SERIE, horizon="2026-Q3",
                         as_of="2026-05-15", point=3.4, intervals=INTERVALOS, h=1,
                         measure=med.DLOG_PCT)
    meta = proc.meta_de(db, fila)
    assert meta.horizon == "2026-Q3"
    assert meta.backtest_id.endswith("|+1T")
    assert meta.n_oos >= MIN_OOS
    ok, motivo = proc.es_publicable(meta)
    assert ok, motivo
