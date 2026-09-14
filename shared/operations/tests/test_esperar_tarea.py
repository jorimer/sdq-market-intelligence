"""``esperar_tarea`` mantiene VIVA la operación mientras el worker trabaja en silencio.

La consola da por «(interrumpido)» a una operación cuyo latido no se renueva en 30 minutos,
y el latido solo se renueva cuando el runner llama a ``set_phase``. Una tarea que no publica
fases —el backfill del SIB trabaja horas sin ``update_state``— dejaba de latir: la consola
la marcaba interrumpida con el worker sano, y el guard «ya en curso» dejaba dispararla OTRA
vez encima de la que seguía corriendo.
"""
import shared.operations.worker as worker


class _Tarea:
    id = "t-1"

    def __init__(self, consultas_hasta_terminar, resultado=None, info=None):
        self._n, self._resultado, self._info = consultas_hasta_terminar, resultado, info

    def ready(self):
        self._n -= 1
        return self._n < 0

    @property
    def info(self):
        return self._info

    def failed(self):
        return False

    @property
    def result(self):
        return self._resultado


def test_una_tarea_sin_fases_sigue_latiendo(monkeypatch):
    monkeypatch.setattr(worker, "_dormir", lambda _s: None)
    llamadas = []
    # 72 consultas × 5 s = 360 s de espera sin una sola fase nueva: 5 latidos de 60 s.
    res = worker.esperar_tarea(_Tarea(72, resultado={"ok": 1}), llamadas.append,
                               espera_maxima_seg=3600, latido_seg=5, al_vencer="x")
    assert res == {"ok": 1, "via": "worker"}
    renovaciones = len(llamadas) - 1                     # la primera es «encolada»
    assert renovaciones >= 360 // worker.LATIDO_CONSOLA_SEG - 1, llamadas
    assert set(llamadas) == {"encolada en el worker"}    # renueva sin inventar una fase


def test_renueva_con_la_ULTIMA_fase_vista(monkeypatch):
    monkeypatch.setattr(worker, "_dormir", lambda _s: None)
    llamadas = []
    worker.esperar_tarea(_Tarea(72, resultado={}, info={"phase": "tipo BAC"}), llamadas.append,
                         espera_maxima_seg=3600, latido_seg=5, al_vencer="x")
    assert llamadas[0] == "encolada en el worker"
    assert set(llamadas[1:]) == {"worker: tipo BAC"}
    # La fase nueva cuenta como latido; después se renueva con ella cada 60 s.
    assert len(llamadas) >= 2 + 360 // worker.LATIDO_CONSOLA_SEG - 1
