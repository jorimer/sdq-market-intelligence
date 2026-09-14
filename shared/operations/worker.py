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

#: Cada cuánto se renueva el latido de la consola aunque la tarea no publique fases. La
#: consola da por «(interrumpido)» a lo que no late en 30 minutos, y eso además destraba el
#: guard «ya en curso»: una tarea silenciosa de horas (el backfill SIB) quedaba marcada
#: interrumpida con el worker sano y se podía disparar otra encima.
LATIDO_CONSOLA_SEG = 60.0


def esperar_tarea(tarea: Any, set_phase: Callable[[str], None], *,
                  espera_maxima_seg: float, latido_seg: float, al_vencer: str) -> Dict:
    """Espera a ``tarea`` (un ``AsyncResult``) y traduce su desenlace al contrato del runner.

    - Mientras corre, retransmite ``tarea.info["phase"]`` (lo que la tarea publica con
      ``update_state``) a ``set_phase``, y renueva el latido cada ``LATIDO_CONSOLA_SEG``
      con la última fase vista aunque no haya una nueva.
    - Si falla, devuelve ``{"error": ...}``: es lo que el console escribe en ``status.error``.
    - Si vence la espera, devuelve ``{"error": al_vencer}`` SIN cancelar la tarea. Dejar de
      mirar no es lo mismo que fallar, pero tampoco es un «completado»: se declara.
    - Si termina bien, devuelve el resultado del worker con ``via="worker"``.
    """
    actual = "encolada en el worker"
    set_phase(actual)
    espera, sin_latir, visto = 0.0, 0.0, None
    while not tarea.ready():
        if espera >= espera_maxima_seg:
            return {"error": al_vencer, "task_id": tarea.id}
        info = tarea.info if isinstance(tarea.info, dict) else None
        frase = (info or {}).get("phase")
        if frase and frase != visto:
            actual, visto = f"worker: {frase}", frase
            set_phase(actual)
            sin_latir = 0.0
        elif sin_latir >= LATIDO_CONSOLA_SEG:
            set_phase(actual)
            sin_latir = 0.0
        _dormir(latido_seg)
        espera += latido_seg
        sin_latir += latido_seg
    if tarea.failed():
        return {"error": f"la tarea del worker falló: {tarea.result}", "task_id": tarea.id}
    resultado = tarea.result
    if not isinstance(resultado, dict):
        resultado = {"resultado": resultado}
    return {**resultado, "via": "worker"}


def disparar_desde_ruta(operacion: str, *, user_id: Any, params: Dict, mensaje: str) -> Dict:
    """La mitad de RUTA del mismo contrato: una ruta no espera al worker, dispara una operación.

    Esperar dentro del request no es opción —el proxy corta a los ~270 s y estas tareas
    duran de minutos a horas—. Así que la ruta responde al instante, pero lo que corre es
    una operación de consola cuyo runner espera con :func:`esperar_tarea`: el desenlace real,
    o el error, queda en ``status.error`` de ``GET /api/v1/operations/status``.

    Conserva las claves que las pantallas ya leen (``status``, ``message``).
    """
    from shared.operations.service import trigger

    r = trigger(operacion, origin="manual", user_id=user_id, params=params)
    if r.get("started"):
        return {"status": "started", "via": "consola", "operation": operacion,
                "run_id": r.get("run_id"), "message": mensaje}
    return {"status": "not_started", "operation": operacion,
            "message": r.get("reason") or "No se pudo iniciar la operación."}
