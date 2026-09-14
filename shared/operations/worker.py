"""Esperar desde el runner a una tarea que corre en el worker de Celery.

**Por qué existe.** El console marca «completado» apenas el runner devuelve. Un runner que
encola y vuelve le dice al console que la operación terminó bien cuando el worker recién
empezó, y lo que el worker levante después (un ``TramitesSyncError``, un
``StringDataRightTruncation`` de Postgres) no llega NUNCA a ``status.error``. Quien verifica
por la consola —la manera documentada: leer ``status.error``, no ``last_result``— recibe un
OK falso. Le pasó a ``tramites-registro-unico`` el 2026-09-14: ``phase='completado'`` en un
segundo mientras el worker seguía leyendo ~710 fichas del catálogo.

El hilo que espera no cuesta memoria: el trabajo pesado corre del otro lado, que es todo el
punto de mandarlo al worker. Lo vigila
``shared/operations/tests/test_runner_espera_al_worker.py``.
"""
import time
from typing import Any, Callable, Dict

#: Indirección para que los tests no duerman de verdad.
_dormir = time.sleep


def esperar_tarea(tarea: Any, set_phase: Callable[[str], None], *,
                  espera_maxima_seg: float, latido_seg: float, al_vencer: str) -> Dict:
    """Espera a ``tarea`` (un ``AsyncResult``) y traduce su desenlace al contrato del runner.

    - Mientras corre, retransmite ``tarea.info["phase"]`` (lo que la tarea publica con
      ``update_state``) a ``set_phase``.
    - Si falla, devuelve ``{"error": ...}``: es lo que el console escribe en ``status.error``.
    - Si vence la espera, devuelve ``{"error": al_vencer}`` SIN cancelar la tarea. Dejar de
      mirar no es lo mismo que fallar, pero tampoco es un «completado»: se declara.
    - Si termina bien, devuelve el resultado del worker con ``via="worker"``.
    """
    set_phase("encolada en el worker")
    espera, visto = 0.0, None
    while not tarea.ready():
        if espera >= espera_maxima_seg:
            return {"error": al_vencer, "task_id": tarea.id}
        info = tarea.info if isinstance(tarea.info, dict) else None
        frase = (info or {}).get("phase")
        if frase and frase != visto:
            set_phase(f"worker: {frase}")
            visto = frase
        _dormir(latido_seg)
        espera += latido_seg
    if tarea.failed():
        return {"error": f"la tarea del worker falló: {tarea.result}", "task_id": tarea.id}
    resultado = tarea.result
    if not isinstance(resultado, dict):
        resultado = {"resultado": resultado}
    return {**resultado, "via": "worker"}
