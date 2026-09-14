"""El runner de trámites ESPERA al worker y le pasa al console su desenlace.

El 2026-09-14 ``_run_tramites`` encolaba y devolvía: el console decía «completado» con
``error=None`` mientras el worker seguía leyendo el catálogo, y un fallo del worker nunca
llegaba a ``status.error``. Estos tests simulan la tarea de Celery; no hay broker.
"""
import pytest

import shared.operations.worker as worker
from modules.social_dev import operations as ops


class _TareaFalsa:
    """Un ``AsyncResult`` mínimo: ``ready()`` pasa a True tras ``latidos`` consultas."""

    id = "tarea-123"

    def __init__(self, *, latidos=1, falla=None, resultado=None, fases=()):
        self._latidos, self._falla, self._resultado = latidos, falla, resultado
        self._fases = list(fases)
        self.revocada = False

    def ready(self):
        if self._latidos <= 0:
            return True
        self._latidos -= 1
        return False

    @property
    def info(self):
        if self._latidos > 0:
            return {"phase": self._fases[0]} if self._fases else None
        return self._falla if self._falla else self._resultado

    def failed(self):
        return self.ready() and self._falla is not None

    @property
    def result(self):
        return self._falla if self._falla is not None else self._resultado

    def revoke(self, *a, **k):                         # pragma: no cover - no debe llamarse
        self.revocada = True


@pytest.fixture()
def con_broker(monkeypatch):
    from shared.config.settings import settings
    from modules.social_dev import tasks

    monkeypatch.setattr(settings, "USE_CELERY", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://falso:6379/0")
    monkeypatch.setattr(worker, "_dormir", lambda _s: None)
    encoladas = []

    def encolar(tarea):
        def delay(**kwargs):
            encoladas.append(kwargs)
            return tarea
        monkeypatch.setattr(tasks.tramites_registro_unico_task, "delay", delay)
        return encoladas
    return encolar


def _correr(params=None):
    fases = []
    return ops._run_tramites(params or {}, None, fases.append), fases


def test_una_tarea_que_FALLA_devuelve_error(con_broker):
    from modules.social_dev.tramites_sync import TramitesSyncError

    con_broker(_TareaFalsa(latidos=2, falla=TramitesSyncError("catálogo con 3 fichas"),
                           fases=["leyendo catálogo"]))
    resultado, fases = _correr()
    assert "catálogo con 3 fichas" in resultado["error"]
    assert resultado.get("via") != "worker"
    assert "encolada en el worker" in fases and "worker: leyendo catálogo" in fases


def test_una_tarea_que_TERMINA_devuelve_el_resultado_del_worker(con_broker):
    encoladas = con_broker(_TareaFalsa(latidos=3, resultado={"persistidos": 3,
                                                             "periodo": "2026-09"}))
    resultado, _ = _correr({"force": False})
    assert resultado == {"persistidos": 3, "periodo": "2026-09", "via": "worker"}
    assert "error" not in resultado
    assert encoladas == [{"force": False}]


def test_un_error_DECLARADO_por_el_worker_llega_como_error(con_broker):
    con_broker(_TareaFalsa(latidos=0, resultado={"error": "catálogo vacío"}))
    resultado, _ = _correr()
    assert resultado["error"] == "catálogo vacío"


def test_si_vence_la_espera_se_DECLARA_y_no_se_cancela(con_broker, monkeypatch):
    monkeypatch.setattr(ops, "_ESPERA_MAXIMA_SEG", 10)
    tarea = _TareaFalsa(latidos=10_000)
    con_broker(tarea)
    resultado, _ = _correr()
    assert "dejamos de mirar" in resultado["error"]
    assert tarea.revocada is False


def test_el_console_escribe_el_fallo_del_worker_en_status_error(con_broker, monkeypatch):
    """Un test del runner no es un test de la ruta: lo que se verifica en prod es
    ``status.error``, así que se lee ahí, pasando por ``trigger``."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import shared.operations.service as svc
    from shared.auth.models import User
    from shared.database.base import Base
    from shared.operations.models import OperationRun
    from shared.settings.models import AppSetting

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, OperationRun.__table__,
                                             AppSetting.__table__])
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(svc, "SessionLocal", Session)
    monkeypatch.setattr(svc, "_spawn", lambda fn: fn())
    monkeypatch.setattr(svc, "_fire_cascade", lambda *_a: None)
    con_broker(_TareaFalsa(latidos=1, falla=RuntimeError("StringDataRightTruncation")))

    assert svc.trigger("tramites-registro-unico")["started"] is True
    s = Session()
    try:
        status = svc.get_status(s, "tramites-registro-unico")
    finally:
        s.close()
    assert status["phase"] == "error"
    assert "StringDataRightTruncation" in status["error"]
