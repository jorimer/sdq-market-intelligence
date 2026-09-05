"""El ledger de pronósticos: se escribe antes que el modelo, y no se puede maquillar.

El track record es parte del producto, no un subproducto. Todo lo que este archivo fija
existe porque hay una manera concreta de reescribir la historia sin querer:

* **`revision` está en la clave.** Con una clave de cuatro campos, una corrección de un
  pronóstico ya emitido no se puede escribir —colisiona— y el único camino queda ser
  actualizar la fila original, que es reescribir la historia. Con `revision`, la corrección
  entra como fila nueva y **las dos quedan**.
* **`status` y linaje son dos ejes, en dos columnas.** Poner `"superseded"` como `status`
  reabre el maquillaje por otra puerta: el track record se computa sobre `revision = 0` en
  estado `scored`, así que marcar la revisión 0 como superseded la saca del cómputo — y
  corregir un pronóstico habría borrado el original del historial.
* **La puntuación es automática.** Un proceso que depende de que alguien se acuerde deja de
  correr el trimestre en que el resultado es malo.
* **Se puntúan LOS DOS niveles de intervalo.** Un modelo cuyo intervalo del 80% acierta el
  45% de las veces está mal calibrado aunque su error medio sea bajo, y quien dimensiona
  riesgo con ese intervalo se equivoca.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import ledger
from modules.macro_monitor.forecasting.models import ForecastLog
from modules.macro_monitor.models.models import MacroSeries
from shared.database.base import Base

SERIE = "bcrd.xls.pib_2018.serie_original_indice"
MODELO = "bridge_imae_pib.m2.v1"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _registrar(db, **cambios):
    # `h` = horizonte RELATIVO, y sin él la fila queda fuera de todo conjunto de track
    # record a propósito: ver `test_horizonte_relativo.py`. Que el fixture lo pase es parte
    # del contrato, no un detalle — una fila sin `h` no se puntúa contra nada.
    base = dict(model_id=MODELO, target_series=SERIE, horizon="2026-Q1",
                as_of="2025-11-15", revision=0, point=100.0, h=1,
                intervals=[[0.80, 98.0, 102.0], [0.90, 97.0, 103.0]])
    base.update(cambios)
    return ledger.registrar(db, **base)


# ── La clave de CINCO campos ────────────────────────────────────────────────────────
def test_el_mismo_pronostico_dos_veces_no_entra_dos_veces(db):
    _registrar(db)
    with pytest.raises(IntegrityError):
        _registrar(db)


def test_una_correccion_entra_como_fila_nueva_y_LAS_DOS_QUEDAN(db):
    original = _registrar(db)
    correccion = _registrar(db, revision=1, point=101.0)
    assert original.id != correccion.id
    assert db.query(ForecastLog).count() == 2


def test_la_revision_0_sigue_contando_en_el_track_record(db):
    """Corregir un pronóstico no puede borrar el original del historial: es exactamente lo
    que `revision` viene a impedir."""
    _registrar(db)
    _registrar(db, revision=1, point=101.0)
    _observado(db, "2026-Q1", 99.0)
    ledger.puntuar_pendientes(db)
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 1))
    assert tr["n_oos"] == 1, (
        "la revisión 0 desapareció del track record al aparecer una corrección")


def test_el_linaje_no_vive_en_status(db):
    original = _registrar(db)
    correccion = _registrar(db, revision=1, point=101.0)
    ledger.marcar_superseded(db, original, correccion)
    db.refresh(original)
    assert original.superseded_by == correccion.id
    assert original.status in ("pending", "scored"), (
        f"el linaje se coló en `status`: {original.status!r}. El track record se computa "
        "sobre revision=0 y scored; un `superseded` ahí borra el original del cómputo.")


def test_status_solo_admite_dos_valores():
    assert set(ledger.ESTADOS) == {"pending", "scored"}


# ── Puntuación ─────────────────────────────────────────────────────────────────────
def _observado(db, periodo, valor):
    db.add(MacroSeries(series_code=SERIE, period=periodo, value=valor))
    db.commit()


def test_no_puntua_lo_que_todavia_no_tiene_observado(db):
    _registrar(db)
    assert ledger.puntuar_pendientes(db) == 0
    assert db.query(ForecastLog).one().status == "pending"


def test_puntua_solo_cuando_llega_el_dato_y_calcula_los_errores(db):
    _registrar(db)
    _observado(db, "2026-Q1", 99.0)
    assert ledger.puntuar_pendientes(db) == 1
    f = db.query(ForecastLog).one()
    assert f.status == "scored"
    assert f.realized == 99.0
    assert f.abs_error == pytest.approx(1.0)
    assert f.sq_error == pytest.approx(1.0)
    assert f.scored_at is not None


def test_puntua_LOS_DOS_niveles_de_intervalo(db):
    _registrar(db)
    _observado(db, "2026-Q1", 102.5)      # fuera del 80% (98–102), dentro del 90% (97–103)
    ledger.puntuar_pendientes(db)
    f = db.query(ForecastLog).one()
    assert f.interval_hit_80 is False
    assert f.interval_hit_90 is True


def test_puntuar_dos_veces_no_cambia_nada(db):
    _registrar(db)
    _observado(db, "2026-Q1", 99.0)
    ledger.puntuar_pendientes(db)
    assert ledger.puntuar_pendientes(db) == 0


def test_un_observado_nulo_no_puntua(db):
    """«El período existe con valor nulo» no es «llegó el dato»."""
    _registrar(db)
    _observado(db, "2026-Q1", None)
    assert ledger.puntuar_pendientes(db) == 0


# ── Track record y su lectura ───────────────────────────────────────────────────────
def test_el_track_record_trae_error_y_cobertura_de_LOS_DOS_niveles(db):
    # 102,5 cae FUERA del 80% (98–102) y DENTRO del 90% (97–103): es el caso que
    # distingue los dos niveles. Con 104 quedaba fuera de los dos y el test no probaba nada
    # sobre el 90% — la aritmética la hice después de escribir la expectativa, y no al revés.
    for i, (as_of, obs) in enumerate([("2025-01-15", 99.0), ("2025-04-15", 101.0),
                                      ("2025-07-15", 102.5)]):
        _registrar(db, as_of=as_of, horizon=f"2025-Q{i + 1}")
        _observado(db, f"2025-Q{i + 1}", obs)
    ledger.puntuar_pendientes(db)
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, None))
    assert tr["n_oos"] == 3
    assert tr["rmse"] > 0
    cobertura = dict((lv, c) for lv, c, _n in tr["interval_coverage"])
    assert cobertura[0.80] == pytest.approx(2 / 3)   # 102,5 se sale del 80%
    assert cobertura[0.90] == pytest.approx(1.0)


def test_el_track_record_ignora_las_correcciones(db):
    _registrar(db)
    _registrar(db, revision=1, point=99.0)
    _observado(db, "2026-Q1", 99.0)
    ledger.puntuar_pendientes(db)
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 1))
    assert tr["n_oos"] == 1, "una corrección infló el track record"
    assert tr["rmse"] == pytest.approx(1.0), (
        "el track record usó la corrección: mide el pronóstico como se PUBLICÓ")
