"""Un trimestre objetivo cuenta UNA vez en el conjunto, por más veces que se lo re-emita.

`n_oos` contaba EMISIONES, no trimestres. Y la emisión se dispara en cascada tras cada
ingesta canónica, así que un mismo trimestre objetivo se re-emite varias veces antes de
cerrar — cada corrida en otra fecha escribe una fila nueva, porque `as_of` está en la clave
de cinco campos. Medido: cuatro trimestres de evidencia real daban `n_oos = 12` y el gate,
que exige doce, ADMITÍA.

Es lo que este ledger existe para impedir. El `backtest_id` se diseñó sobre el supuesto de
que «un trimestre se pronostica una sola vez a cada distancia» —lo dice su propio docstring—
y la re-emisión lo rompe sin que nada avise.

**Y una re-emisión no es evidencia nueva.** Si viene del MISMO bloque es el mismo pronóstico
re-sellado: el conjunto de información no cambió. Y si el bloque avanzó, el horizonte
relativo cambia —2026-Q3 pasa de h=2 a h=1— y la fila cae en otro conjunto sola. O sea que
varias `as_of` para el mismo horizonte DENTRO de un conjunto implican el mismo bloque.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import ledger
from shared.data import medida_de_pronostico as med
from shared.database.base import Base
from shared.registry.projection import MIN_OOS

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


def _emitir(db, *, horizonte, as_of, error, h=2, punto=5.5):
    f = ledger.registrar(db, model_id=MODELO, target_series=SERIE, horizon=horizonte,
                         as_of=as_of, point=punto, h=h, measure=med.YOY_PCT,
                         intervals=[[0.80, punto - 2, punto + 2]])
    f.status, f.realized = "scored", punto + error
    f.abs_error, f.sq_error, f.interval_hit_80 = abs(error), error ** 2, True
    db.commit()
    return f


def _tr(db, h=2):
    return ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, h, med.YOY_PCT))


# ── El conteo ───────────────────────────────────────────────────────────────────────


def test_cuatro_trimestres_re_emitidos_NO_son_doce_observaciones(db):
    """El caso medido en producción: el sync dispara la emisión y cada corrida en otra fecha
    escribe una fila. Con doce filas sobre cuatro trimestres, el gate se abría."""
    trimestres = ["2026-Q3", "2026-Q4", "2027-Q1", "2027-Q2"]
    for i, hor in enumerate(trimestres):
        for k in range(3):
            _emitir(db, horizonte=hor, as_of=f"2026-{6 + i * 3 + k:02d}-06", error=0.4)

    tr = _tr(db)
    assert tr["n_oos"] == len(trimestres), (
        f"el conjunto cuenta {tr['n_oos']} observaciones sobre {len(trimestres)} trimestres "
        f"de evidencia real; el gate exige {MIN_OOS} y se abriría con un tercio de la muestra")


def test_trimestres_DISTINTOS_si_suman(db):
    """El contraejemplo. Sin él, un `_del_conjunto` que devolviera una sola fila siempre
    pasaría el test de arriba y el track record no crecería nunca."""
    for i, hor in enumerate(["2026-Q3", "2026-Q4", "2027-Q1"]):
        _emitir(db, horizonte=hor, as_of=f"2026-{6 + i * 3:02d}-06", error=0.4)
    assert _tr(db)["n_oos"] == 3


def test_manda_la_emision_ORIGINAL_y_no_la_ultima(db):
    """El pronóstico como se PUBLICÓ, que es la misma doctrina que rige para las revisiones.
    Con el mismo bloque las dos son idénticas; el criterio importa el día que no lo sean."""
    _emitir(db, horizonte="2026-Q3", as_of="2026-06-06", error=0.4, punto=5.5)
    _emitir(db, horizonte="2026-Q3", as_of="2026-07-06", error=3.0, punto=8.0)
    tr = _tr(db)
    assert tr["n_oos"] == 1
    assert tr["rmse"] == pytest.approx(0.4), (
        f"el track record tomó la re-emisión (RMSE {tr['rmse']}) en vez de la original (0,4)")


def test_el_error_no_se_sesga_hacia_el_trimestre_MAS_RE_EMITIDO(db):
    """No es solo el conteo: con tres filas de un trimestre y una de otro, el error del
    primero pesaba el triple. El promedio quedaba inclinado por cuántas veces corrió una
    operación, que es un criterio sin ningún sentido."""
    for k in range(3):
        _emitir(db, horizonte="2026-Q3", as_of=f"2026-0{6 + k}-06", error=0.0)
    _emitir(db, horizonte="2026-Q4", as_of="2026-09-06", error=4.0)
    tr = _tr(db)
    assert tr["n_oos"] == 2
    # dos trimestres, errores 0 y 4 → RMSE = sqrt((0 + 16)/2)
    assert tr["rmse"] == pytest.approx((16 / 2) ** 0.5)


# ── El solapamiento, que ahora significa lo que su docstring decía ──────────────────


def test_a_DOS_trimestres_vista_con_emision_trimestral_SI_solapan(db):
    """El resultado estándar: pronósticos a `h` pasos emitidos cada `paso` períodos comparten
    información cuando `paso < h`, y sus errores quedan autocorrelacionados. Con h=2 y
    emisión trimestral, `1 < 2`. Esto NO se declaraba."""
    for i, hor in enumerate(["2026-Q3", "2026-Q4", "2027-Q1"]):
        _emitir(db, horizonte=hor, as_of=f"2026-{6 + i * 3:02d}-06", error=0.4, h=2)
    assert _tr(db, 2)["overlapping"] is True


def test_a_UN_trimestre_vista_NO_solapan(db):
    """`1 < 1` es falso. Escribir «no se solapan» donde no se solapan sería ruido, pero
    marcarlo donde no ocurre vacía el aviso de significado."""
    for i, hor in enumerate(["2026-Q3", "2026-Q4", "2027-Q1"]):
        _emitir(db, horizonte=hor, as_of=f"2026-{6 + i * 3:02d}-06", error=0.4, h=1)
    assert _tr(db, 1)["overlapping"] is False


def test_un_conjunto_de_UNA_fila_no_solapa_con_nada(db):
    _emitir(db, horizonte="2026-Q3", as_of="2026-06-06", error=0.4, h=2)
    assert _tr(db, 2)["overlapping"] is False


def test_un_horizonte_que_no_es_un_TRIMESTRE_no_se_puede_juzgar(db):
    """«No sé» no es «no se solapan». El gate ya rechaza el `None` con su motivo; devolver
    `False` afirmaría que se comprobó."""
    _emitir(db, horizonte="+4T", as_of="2026-06-06", error=0.4, h=2)
    _emitir(db, horizonte="2027-Q1", as_of="2026-09-06", error=0.4, h=2)
    assert _tr(db, 2)["overlapping"] is None
