"""Una corrida que HIZO el trabajo mueve la agenda, sea manual o agendada.

**El defecto, medido en prod el 2026-09-15.** `macro-canonical-sync` había corrido el 6 de
septiembre (108.861 registros persistidos, «completado»), y su agenda seguía diciendo
`last_run_at: 2026-08-22`, con la próxima calculada desde agosto. Solo el scheduler tocaba
esas dos columnas —en `run_due_schedules`, al disparar—, así que toda corrida manual quedaba
invisible para la cadencia: el reloj sigue corriendo desde la última corrida AUTOMÁTICA y la
agendada vuelve a hacer el trabajo que alguien acaba de hacer a mano.

Y el dato se publica: `law_intel/informe_abierto.py` lee `last_run_at` para decir cuándo
corrió la operación. Una fecha vieja ahí es una afirmación falsa en un entregable.

**Los dos límites del arreglo.** Una corrida que FALLA no mueve nada —si moviera la próxima,
un fallo aplazaría el reintento—. Y una corrida con parámetros distintos de los de la agenda
registra su `last_run_at` pero NO pospone la próxima: un barrido manual acotado
(`{"limit": 1}`) no es el trabajo completo que la agenda tiene que hacer.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.operations.service as svc
from shared.auth.models import User
from shared.database.base import Base
from shared.operations.calendario import proximo_disparo
from shared.operations.models import OperationRun, OperationSchedule
from shared.operations.service import OPERATIONS, Operation, register_operation
from shared.settings.models import AppSetting

_VIEJO_ULTIMO = datetime(2026, 8, 22, 21, 20)
_VIEJO_PROXIMO = datetime(2026, 9, 21, 21, 20)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        OperationSchedule.__table__, OperationRun.__table__, AppSetting.__table__,
        User.__table__,
    ])
    return sessionmaker(bind=engine)


@pytest.fixture()
def consola(Session, monkeypatch):
    """Consola en modo síncrono: `trigger` corre el runner en este hilo."""
    guardadas = dict(OPERATIONS)
    OPERATIONS.clear()
    monkeypatch.setattr(svc, "SessionLocal", Session)
    monkeypatch.setattr(svc, "_spawn", lambda fn: fn())
    monkeypatch.setattr(svc, "_fire_cascade", lambda *_a: None)
    try:
        yield
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(guardadas)


def _agendar(Session, op_name, *, enabled=True, interval=720, params=None):
    s = Session()
    try:
        s.add(OperationSchedule(operation=op_name, enabled=enabled, interval_hours=interval,
                                params=params, next_run_at=_VIEJO_PROXIMO,
                                last_run_at=_VIEJO_ULTIMO))
        s.commit()
    finally:
        s.close()


def _agenda(Session, op_name):
    s = Session()
    try:
        return s.query(OperationSchedule).filter_by(operation=op_name).one()
    finally:
        s.close()


def test_una_corrida_manual_exitosa_mueve_la_agenda(Session, consola):
    register_operation(Operation("cano", "Canónica", "d", lambda *a: {"files": 34}, 720))
    _agendar(Session, "cano")
    antes = svc._dt()

    assert svc.trigger("cano")["started"] is True

    fila = _agenda(Session, "cano")
    assert fila.last_run_at >= antes, "la corrida manual no movió last_run_at"
    # La próxima se recalcula desde AHORA, no desde la corrida automática de agosto.
    esperado = antes + timedelta(hours=720)
    assert fila.next_run_at >= esperado - timedelta(minutes=1)
    assert fila.next_run_at != _VIEJO_PROXIMO


def test_una_corrida_que_devuelve_error_NO_mueve_la_agenda(Session, consola):
    register_operation(Operation("cano", "Canónica", "d", lambda *a: {"error": "sin CDN"}, 720))
    _agendar(Session, "cano")

    svc.trigger("cano")

    fila = _agenda(Session, "cano")
    assert fila.last_run_at == _VIEJO_ULTIMO
    assert fila.next_run_at == _VIEJO_PROXIMO, "un fallo aplazaría el reintento"


def test_una_corrida_que_REVIENTA_tampoco_mueve_la_agenda(Session, consola):
    def revienta(*_a):
        raise RuntimeError("proxy caído")

    register_operation(Operation("cano", "Canónica", "d", revienta, 720))
    _agendar(Session, "cano")

    svc.trigger("cano")

    fila = _agenda(Session, "cano")
    assert fila.last_run_at == _VIEJO_ULTIMO and fila.next_run_at == _VIEJO_PROXIMO


def test_con_OTROS_parametros_registra_la_corrida_pero_no_pospone(Session, consola):
    """Un barrido manual de un archivo no es el barrido completo que la agenda debe hacer."""
    register_operation(Operation("barrido", "Barrido", "d", lambda *a: {"processed": 1}, 720))
    _agendar(Session, "barrido", params={})
    antes = svc._dt()

    svc.trigger("barrido", params={"limit": 1})

    fila = _agenda(Session, "barrido")
    assert fila.last_run_at >= antes, "corrió: last_run_at es un hecho, aunque sea acotada"
    assert fila.next_run_at == _VIEJO_PROXIMO, "no hizo el trabajo completo: no pospone"


def test_con_anclaje_la_proxima_la_fija_el_CALENDARIO(Session, consola):
    """La cadencia anclada no se vuelve relativa por pasar por acá."""
    register_operation(Operation("trim", "Trimestral", "d", lambda *a: {}, 2160,
                                 anclaje="trimestral"))
    _agendar(Session, "trim", interval=2160)
    antes = svc._dt()

    svc.trigger("trim")

    fila = _agenda(Session, "trim")
    calendario = proximo_disparo("trimestral", antes, 2160, None)
    assert abs((fila.next_run_at - calendario).total_seconds()) < 120
    assert fila.next_run_at < antes + timedelta(hours=2160), "quedó relativa, no anclada"


def test_una_agenda_APAGADA_registra_la_corrida_y_no_programa(Session, consola):
    register_operation(Operation("cano", "Canónica", "d", lambda *a: {}, 720))
    _agendar(Session, "cano", enabled=False)
    antes = svc._dt()

    svc.trigger("cano")

    fila = _agenda(Session, "cano")
    assert fila.last_run_at >= antes
    assert fila.next_run_at == _VIEJO_PROXIMO


def test_sin_fila_de_agenda_la_corrida_termina_igual(Session, consola):
    """Una operación bajo demanda no tiene agenda: el arreglo no puede romperla."""
    register_operation(Operation("puntual", "Puntual", "d", lambda *a: {"ok": 1}, 0))

    assert svc.trigger("puntual")["started"] is True

    s = Session()
    try:
        fila = s.query(OperationRun).filter_by(operation="puntual").one()
        assert fila.status == "completed"
        assert s.query(OperationSchedule).filter_by(operation="puntual").first() is None
    finally:
        s.close()
