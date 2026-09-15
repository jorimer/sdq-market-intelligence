"""El backfill SIB disparado desde la pantalla deja su desenlace en la consola.

`POST /banking-score/data/sib-backfill` encolaba en el worker y respondía: si el worker
fallaba, el error no llegaba a ningún estado de la consola. Ahora la ruta dispara la operación
`sib-backfill`, que encola y espera. Y `run_backfill` dice sus fallos como
``{"status": "error"}``, que la consola no reconoce: se traduce, o el fallo queda «completado».
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import shared.operations.worker as worker
from app.main import app
from modules.banking_score import operations as ops
from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole


class _Tarea:
    id = "t-sib"

    def __init__(self, *, falla=None, resultado=None):
        self._falla, self._resultado = falla, resultado

    def ready(self):
        return True

    @property
    def info(self):
        return None

    def failed(self):
        return self._falla is not None

    @property
    def result(self):
        return self._falla if self._falla is not None else self._resultado


@pytest.fixture()
def sin_broker(monkeypatch):
    from shared.config.settings import settings
    monkeypatch.setattr(settings, "USE_CELERY", False)


@pytest.fixture()
def con_broker(monkeypatch):
    from shared.config.settings import settings
    from modules.banking_score import tasks

    monkeypatch.setattr(settings, "USE_CELERY", True)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://falso:6379/0")
    monkeypatch.setattr(worker, "_dormir", lambda _s: None)

    def encolar(tarea):
        llamadas = []
        monkeypatch.setattr(tasks.sib_backfill_task, "delay",
                            lambda **kw: (llamadas.append(kw), tarea)[1])
        return llamadas
    return encolar


class TestElRunnerTraduceLosFallosDeRunBackfill:
    def test_sin_broker_un_status_error_llega_como_error(self, sin_broker, monkeypatch):
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill",
                            lambda **kw: {"status": "error", "message": "La clave SIB no está"})
        r = ops._run_sib_backfill({}, None, lambda _f: None)
        assert r["error"] == "La clave SIB no está"
        assert r["via"] == "proceso_web"

    def test_ya_en_curso_tampoco_es_completado(self, sin_broker, monkeypatch):
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill",
                            lambda **kw: {"status": "already_running", "message": "Ya hay una"})
        assert ops._run_sib_backfill({}, None, lambda _f: None)["error"] == "Ya hay una"

    def test_un_resultado_bueno_no_se_toca(self, sin_broker, monkeypatch):
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill",
                            lambda **kw: {"status": "completed", "records": 10})
        r = ops._run_sib_backfill({}, None, lambda _f: None)
        assert "error" not in r and r["records"] == 10

    def test_el_sync_liviano_tambien_traduce(self, monkeypatch):
        """Mismo defecto en la operación agendada: su fallo quedaba «completado»."""
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill",
                            lambda **kw: {"status": "error", "message": "SIB caída"})
        assert ops._run_sib_sync_liviano({}, None, lambda _f: None)["error"] == "SIB caída"


class TestSinWorkerLaConsolaSigueLatiendo:
    """El sync que corre EN el proceso latía una sola vez, al arrancar.

    Pasó en producción el 2026-09-15: `sib-sync-liviano` —re-ingesta de 40+ minutos— quedó
    «(interrumpido)» a los 30 minutos con la carga viva, porque la consola da por muerto lo que
    no late en ese lapso y `run_backfill` escribe su avance en OTRO registro. Quien leía la
    consola regeneró un informe a media carga; y el guard «ya en curso» quedó destrabado para
    disparar una segunda sincronización encima. El backfill por worker ya latía; éste no.
    """

    @staticmethod
    def _backfill_lento(fases_publicadas):
        import time as _t

        def run_backfill(**kw):
            for f in ("extrayendo BM (1/7)", "extrayendo AC (7/7)", "calculando ratings"):
                fases_publicadas.append(f)
                _t.sleep(0.05)
            return {"status": "completed", "records": 3}
        return run_backfill

    def test_el_sync_liviano_late_mientras_corre_y_retransmite_la_fase(self, monkeypatch):
        publicadas, vistas = [], []
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill",
                            self._backfill_lento(publicadas))
        monkeypatch.setattr("modules.banking_score.sib_sync.get_sync_status",
                            lambda *a, **k: {"phase": publicadas[-1] if publicadas else ""})
        monkeypatch.setattr(ops, "_LATIDO_SIB_EN_PROCESO_SEG", 0.01, raising=False)
        r = ops._run_sib_sync_liviano({}, None, vistas.append)
        assert r["records"] == 3 and "error" not in r
        assert len(vistas) >= 4, f"la consola latió {len(vistas)} vez/veces: queda muda"
        assert any("calculando ratings" in v for v in vistas), vistas

    def test_un_fallo_del_backfill_sigue_llegando_como_error(self, monkeypatch):
        def revienta(**kw):
            raise RuntimeError("proxy SIB 504")
        monkeypatch.setattr("modules.banking_score.sib_sync.run_backfill", revienta)
        monkeypatch.setattr(ops, "_LATIDO_SIB_EN_PROCESO_SEG", 0.01, raising=False)
        with pytest.raises(RuntimeError, match="proxy SIB 504"):
            ops._run_sib_sync_liviano({}, None, lambda _f: None)


class TestConBrokerEsperaAlWorker:
    def test_una_tarea_que_FALLA_devuelve_error(self, con_broker):
        con_broker(_Tarea(falla=RuntimeError("StringDataRightTruncation")))
        r = ops._run_sib_backfill({}, None, lambda _f: None)
        assert "StringDataRightTruncation" in r["error"]

    def test_el_worker_que_devuelve_status_error_llega_como_error(self, con_broker):
        con_broker(_Tarea(resultado={"status": "error", "message": "proxy SIB 504"}))
        r = ops._run_sib_backfill({}, None, lambda _f: None)
        assert r["error"] == "proxy SIB 504" and r["via"] == "worker"

    def test_pasa_los_parametros_a_la_tarea(self, con_broker):
        llamadas = con_broker(_Tarea(resultado={"status": "completed"}))
        ops._run_sib_backfill({"force": True, "only_tipos": ["BAC"], "skip_carteras": True},
                              None, lambda _f: None)
        assert llamadas == [{"force": True, "only_tipos": ["BAC"], "skip_carteras": True}]


def test_la_operacion_esta_registrada_bajo_demanda():
    from shared.operations.service import OPERATIONS, is_on_demand

    # `register()` reemplaza las operaciones del módulo por objetos nuevos y les borra los
    # `triggers` que `enganchar_cascada()` agregó al arrancar: sin restaurar, este test
    # rompía `test_cascada` al correr antes que él.
    guardadas = dict(OPERATIONS)
    try:
        ops.register()
        op = OPERATIONS["sib-backfill"]
        assert op.runner is ops._run_sib_backfill
        assert is_on_demand(op) is True        # no se agenda sola: el completo tarda horas
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(guardadas)


class TestLaRutaDisparaLaOperacion:
    """Un test del runner no es un test de la ruta: se pide por HTTP."""

    @pytest.fixture()
    def cliente(self, monkeypatch):
        disparos = []

        def trigger(name, origin="manual", user_id=None, params=None):
            disparos.append(SimpleNamespace(name=name, params=params, user_id=user_id))
            return {"started": True, "operation": name, "run_id": "run-1"}

        monkeypatch.setattr("shared.operations.service.trigger", trigger)
        saved = dict(app.dependency_overrides)
        yield TestClient(app), disparos
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)

    @staticmethod
    def _como(rol):
        app.dependency_overrides[get_current_user] = lambda: User(
            id="u1", email="t@sdq.do", password_hash="x", full_name="T", role=rol)

    @pytest.mark.parametrize("ruta", ["sib-backfill", "sib-sync"])
    def test_admin_dispara_sib_backfill(self, cliente, ruta):
        client, disparos = cliente
        self._como(UserRole.admin)
        r = client.post(f"/api/v1/banking-score/data/{ruta}?tipos=BAC,AAP&skip_carteras=true")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "started" and body["run_id"] == "run-1"
        assert body["operation"] == "sib-backfill" and body["message"]
        assert [d.name for d in disparos] == ["sib-backfill"]
        assert disparos[0].params == {"force": False, "only_tipos": ["BAC", "AAP"],
                                      "skip_carteras": True}

    def test_si_la_consola_no_arranca_se_dice_el_motivo(self, cliente, monkeypatch):
        client, _ = cliente
        self._como(UserRole.admin)
        monkeypatch.setattr("shared.operations.service.trigger",
                            lambda *a, **k: {"started": False,
                                             "reason": "Esta operación ya está en curso."})
        body = client.post("/api/v1/banking-score/data/sib-backfill").json()
        assert body["status"] == "not_started"
        assert body["message"] == "Esta operación ya está en curso."

    def test_un_viewer_no_dispara(self, cliente):
        client, disparos = cliente
        self._como(UserRole.viewer)
        assert client.post("/api/v1/banking-score/data/sib-backfill").status_code == 403
        assert disparos == []
