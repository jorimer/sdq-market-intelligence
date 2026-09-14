"""El barrido Excel y la ingesta canónica disparados desde la pantalla dejan su desenlace
en la consola.

Las dos rutas encolaban en el worker y respondían. Y el estado del barrido vivía en un dict
EN MEMORIA del proceso web, que el worker nunca tocaba: con Celery, «corriendo» jamás era
verdad y un fallo del worker entero no quedaba en ningún lado.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import shared.operations.worker as worker
from app.main import app
from modules.macro_monitor import operations as ops
from modules.macro_monitor import service
from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole


class _Tarea:
    id = "t-macro"

    def __init__(self, *, falla=None, resultado=None, fases=()):
        self._falla, self._resultado, self._fases = falla, resultado, list(fases)
        self._actual = None

    def ready(self):
        # Cada consulta sin terminar avanza una fase; `info` se puede leer las veces que sea.
        if self._fases:
            self._actual = self._fases.pop(0)
            return False
        return True

    @property
    def info(self):
        return {"phase": self._actual} if self._actual else None

    def failed(self):
        return self._falla is not None

    @property
    def result(self):
        return self._falla if self._falla is not None else self._resultado


@pytest.fixture()
def con_broker(monkeypatch):
    from shared.config.settings import settings
    from modules.macro_monitor import tasks

    monkeypatch.setattr(settings, "USE_CELERY", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://falso:6379/0")
    monkeypatch.setattr(worker, "_dormir", lambda _s: None)

    def encolar(nombre_tarea, tarea):
        llamadas = []
        monkeypatch.setattr(getattr(tasks, nombre_tarea), "delay",
                            lambda **kw: (llamadas.append(kw), tarea)[1])
        return llamadas
    return encolar


class TestLosRunnersEsperanAlWorker:
    def test_un_barrido_que_FALLA_devuelve_error(self, con_broker):
        con_broker("excel_batch_task", _Tarea(falla=RuntimeError("catálogo ilegible")))
        r = ops._run_excel_batch({}, None, lambda _f: None)
        assert "catálogo ilegible" in r["error"]

    def test_el_barrido_retransmite_el_avance_y_devuelve_el_resultado(self, con_broker):
        llamadas = con_broker("excel_batch_task", _Tarea(
            resultado={"processed": 5, "ok": 4, "flagged": 1, "failed": 0},
            fases=["archivo 3 de 5: x.xlsx"]))
        fases = []
        r = ops._run_excel_batch({"limit": 5, "persist_series": True}, None, fases.append)
        assert r == {"processed": 5, "ok": 4, "flagged": 1, "failed": 0, "via": "worker"}
        assert "worker: archivo 3 de 5: x.xlsx" in fases
        assert llamadas == [{"sector": None, "limit": 5, "use_claude": True,
                             "persist_series": True, "force": False}]

    def test_una_ingesta_canonica_que_FALLA_devuelve_error(self, con_broker):
        llamadas = con_broker("ingest_canonical_task", _Tarea(falla=RuntimeError("sin CDN")))
        r = ops._run_canonical_ingest_manual({"persist": True}, None, lambda _f: None)
        assert "sin CDN" in r["error"]
        assert llamadas == [{"persist": True}]


def test_sin_broker_el_barrido_corre_aca_con_su_avance(monkeypatch):
    from shared.config.settings import settings

    monkeypatch.setattr(settings, "USE_CELERY", False)
    monkeypatch.setattr(ops, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    vistos = {}

    def falso(db, **kw):
        vistos.update(kw)
        return {"processed": 0, "ok": 0, "flagged": 0, "failed": 0}

    monkeypatch.setattr(service, "run_excel_batch", falso)
    fases = []
    r = ops._run_excel_batch({}, None, fases.append)
    assert r["via"] == "proceso_web"
    vistos["progreso"]("archivo 1 de 1: a.xlsx")        # el avance llega a la consola
    assert fases[-1] == "archivo 1 de 1: a.xlsx"


def test_run_excel_batch_avisa_cada_archivo(monkeypatch):
    """El avance sale del motor, no de un dict en memoria que el worker no comparte."""
    entradas = [SimpleNamespace(url=f"u{i}", filename=f"f{i}.xlsx", sector="s")
                for i in (1, 2)]
    monkeypatch.setattr("shared.data.bcrd_excel.catalog.load_catalog", lambda: entradas)

    def revienta(*a, **k):
        raise ValueError("layout raro")

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", revienta)
    monkeypatch.setattr(service, "_upsert_excel_report", lambda db, fields: None)
    fases = []
    r = service.run_excel_batch(SimpleNamespace(rollback=lambda: None), force=True,
                                use_claude=False, progreso=fases.append)
    assert r == {"processed": 2, "ok": 0, "flagged": 0, "failed": 2}
    assert fases == ["archivo 1 de 2: f1.xlsx", "archivo 2 de 2: f2.xlsx"]


def test_la_cobertura_lee_si_corre_de_la_CONSOLA(monkeypatch):
    monkeypatch.setattr("shared.operations.service.get_status",
                        lambda db, op: {"is_running": True, "phase": "worker: archivo 7 de 20",
                                        "started_at": "2026-09-14T20:00:00+00:00",
                                        "error": None} if op == "macro-excel-batch" else {})
    st = service.excel_batch_status(None)
    assert st["is_running"] is True and st["phase"] == "worker: archivo 7 de 20"
    # La pantalla usa done/total solo si total > 0; en 0 cae al conteo persistido.
    assert st["done"] == 0 and st["total"] == 0


def test_las_operaciones_estan_registradas_bajo_demanda():
    from shared.operations.service import OPERATIONS, is_on_demand

    # `register()` reemplaza las operaciones del módulo y les borra los `triggers` que
    # `enganchar_cascada()` agregó al arrancar: sin restaurar, rompía `test_cascada`.
    guardadas = dict(OPERATIONS)
    try:
        ops.register()
        assert OPERATIONS["macro-excel-batch"].runner is ops._run_excel_batch
        assert (OPERATIONS["macro-canonical-ingest-manual"].runner
                is ops._run_canonical_ingest_manual)
        assert is_on_demand(OPERATIONS["macro-excel-batch"]) is True
        assert is_on_demand(OPERATIONS["macro-canonical-ingest-manual"]) is True
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(guardadas)


class TestLasRutasDisparanLaOperacion:
    """Un test del runner no es un test de la ruta: se piden por HTTP."""

    @pytest.fixture()
    def client(self, monkeypatch):
        disparos = []

        def trigger(name, origin="manual", user_id=None, params=None):
            disparos.append(SimpleNamespace(name=name, params=params))
            return {"started": True, "operation": name, "run_id": "run-9"}

        monkeypatch.setattr("shared.operations.service.trigger", trigger)
        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: User(
            id="u1", email="t@sdq.do", password_hash="x", full_name="T", role=UserRole.admin)
        yield TestClient(app), disparos
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)

    def test_el_barrido(self, client):
        c, disparos = client
        r = c.post("/api/v1/macro-monitor/excel/batch?limit=5&persist=true")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "started" and r.json()["message"]
        assert [d.name for d in disparos] == ["macro-excel-batch"]
        assert disparos[0].params == {"sector": None, "limit": 5, "use_claude": True,
                                      "persist_series": True, "force": False}

    def test_la_ingesta_canonica(self, client):
        c, disparos = client
        r = c.post("/api/v1/macro-monitor/excel/ingest-canonical?persist=true")
        assert r.status_code == 200, r.text
        assert r.json()["operation"] == "macro-canonical-ingest-manual"
        assert disparos[0].params == {"persist": True}
