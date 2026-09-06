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
* **Una fila declara CONTRA QUÉ se la puntúa**, y son dos declaraciones: un `series_code`
  observable y la medida en que está el punto. Sin la segunda, el ledger restaba una tasa
  (~0,4) de un índice de volumen (~133) y publicaba 132,75 como error.

El grueso de este archivo usa la medida `level` porque prueba la MECÁNICA de la puntuación
—clave, revisión, linaje, intervalos— con el punto y el observado en la misma unidad. Lo que
prueba la conversión de medida está más abajo, y el camino real de los dos motores
—que emiten una TASA— vive en `test_el_ledger_puntua_contra_lo_que_debe.py`.
"""
import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.forecasting import ledger
from shared.data import medida_de_pronostico as med
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
                # `level`: el punto y el observado en la misma unidad. Es lo que hace que
                # estos tests midan la mecánica del ledger y no la conversión.
                measure=med.LEVEL,
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
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 1, med.LEVEL))
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
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, None, med.LEVEL))
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
    tr = ledger.track_record(db, ledger.backtest_id(MODELO, SERIE, 1, med.LEVEL))
    assert tr["n_oos"] == 1, "una corrección infló el track record"
    assert tr["rmse"] == pytest.approx(1.0), (
        "el track record usó la corrección: mide el pronóstico como se PUBLICÓ")


# ── La fila declara CONTRA QUÉ se la puntúa ─────────────────────────────────────────


def test_una_medida_desconocida_no_entra_al_ledger(db):
    """La puerta del ledger es donde la declaración se puede exigir. Sin default: el que se
    equivoca nunca es el que la escribe a mano."""
    with pytest.raises(ValueError, match="medida"):
        _registrar(db, measure="porcentaje")


def test_una_serie_objetivo_vacia_no_entra_al_ledger(db):
    with pytest.raises(ValueError, match="serie objetivo"):
        _registrar(db, target_series="  ")


def test_una_TASA_se_puntua_contra_la_VARIACION_del_observado(db):
    """El defecto que costaba 132,75 de error: el punto es un Δlog en % y la serie es el
    índice de volumen. Se convierte el observado, no se compara crudo."""
    _registrar(db, point=0.40, measure=med.DLOG_PCT, horizon="2026-Q1",
               intervals=[[0.80, -0.6, 1.4], [0.90, -1.1, 1.9]])
    _observado(db, "2025-Q4", 133.0)
    _observado(db, "2026-Q1", 133.5)
    assert ledger.puntuar_pendientes(db) == 1
    f = db.query(ForecastLog).one()
    esperado = (math.log(133.5) - math.log(133.0)) * 100
    assert float(f.realized) == pytest.approx(esperado, abs=1e-9)
    assert float(f.abs_error) == pytest.approx(abs(esperado - 0.40), abs=1e-9)


def test_una_TASA_sin_el_periodo_ANTERIOR_no_se_puntua(db):
    """Que haya llegado el trimestre del horizonte no alcanza: una variación necesita contra
    qué medirse, y el anterior es el DE CALENDARIO. Con «el anterior que haya» un hueco
    produce un cambio de dos trimestres rotulado de uno."""
    _registrar(db, point=0.40, measure=med.DLOG_PCT, horizon="2026-Q1")
    _observado(db, "2025-Q3", 132.0)        # hay anterior, pero NO el inmediato
    _observado(db, "2026-Q1", 133.5)
    assert ledger.puntuar_pendientes(db) == 0
    assert db.query(ForecastLog).one().status == "pending"


# ── Lo que no puede cerrar se LISTA ─────────────────────────────────────────────────


def test_una_serie_que_no_existe_se_reporta_como_no_puntuable(db):
    """El defecto A tal cual: `pib_real` es el nombre de la variable en el bloque, no una
    serie. Esa fila no está esperando el trimestre — no puede cerrar nunca."""
    _registrar(db, target_series="pib_real", measure=med.DLOG_PCT)
    rotas = ledger.no_puntuables(db)
    assert [r.motivo for r in rotas] == [ledger.SERIE_DESCONOCIDA]
    assert rotas[0].target_series == "pib_real"


def test_un_pendiente_que_solo_espera_el_dato_NO_se_reporta_como_roto(db):
    """El contraejemplo. Sin él, `no_puntuables` podría devolver todo lo pendiente y los dos
    tests pasarían igual, con el instrumento marcando roto lo que solo es paciencia."""
    _registrar(db)
    _observado(db, "2025-Q4", 99.0)          # la serie existe; falta el período del horizonte
    assert ledger.no_puntuables(db) == []


def test_una_fila_sin_medida_declarada_no_se_puntua_ni_desaparece(db):
    """Las filas anteriores a la migración. No se les supone «nivel» —eso es el defecto— y
    tampoco se saltean en silencio: se listan."""
    f = _registrar(db)
    f.measure = None
    db.commit()
    _observado(db, "2026-Q1", 99.0)
    assert ledger.puntuar_pendientes(db) == 0
    assert [r.motivo for r in ledger.no_puntuables(db)] == [ledger.SIN_MEDIDA]
