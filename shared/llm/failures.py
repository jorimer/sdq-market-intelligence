"""Fallo del API de Anthropic: distinguir SIN CRÉDITO de ERROR DEL MODELO.

Por qué existe. Entre el 18-jul y el 23-ago-2026 el saldo de crédito de la organización
estuvo agotado y produjo 961 eventos en Sentry en una sola semana, repartidos en tres
issues que eran la MISMA causa entrando por rutas distintas. El volumen no venía de
reintentos —el reintento de sección ya excluye los 400 por diseño, y el SDK tampoco los
reintenta— sino de que cada sección degradada loguea a ``ERROR`` y la integración de
logging de Sentry convierte todo ``ERROR`` en un evento: un Deep Dive fanea 6 secciones ×
2-4 llamadas, así que UNA generación sin crédito emite decenas de eventos idénticos.

Qué cambia. El saldo agotado es una condición DETERMINISTA y de ORGANIZACIÓN, no un fallo
del modelo: no se arregla reintentando ni rotando la clave, y no dice nada nuevo la
vigésima vez en el mismo minuto. Se reporta UNA vez por operación y por ventana; las
repeticiones bajan a ``WARNING``, que sigue en el log (y como breadcrumb) pero no abre un
evento. El resto de los fallos conserva ``ERROR`` intacto — el ruido a acallar es el del
saldo, no el de los errores reales que quedaban sepultados debajo.

La degradación NO cambia: el llamador sigue cayendo a su fallback como siempre. Esto es
solo cómo se REPORTA.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict

from shared.observability.llm_ledger import current_caller

# Ventana de re-reporte, alineada con el anti-spam del techo de gasto
# (``shared.llm.budget``): un evento por operación por hora. Suficiente para que un
# agotamiento NUEVO vuelva a alertar, y no tanto como para narrar cada sección.
_CREDIT_LOG_WINDOW_SECONDS = 3600.0

_last_credit_log: Dict[str, float] = {}
_lock = threading.Lock()

# El mensaje del 400 es la única señal que trae el saldo agotado: el ``type`` es
# ``invalid_request_error``, igual que un prompt mal formado. Se compara en minúsculas
# sobre el texto porque el SDK no expone un código propio para esta condición.
_CREDIT_MARKERS = ("credit balance is too low",)


def is_credit_exhausted(exc: BaseException) -> bool:
    """¿El fallo es el saldo de crédito de la organización agotado?

    Es un 400 permanente: reintentarlo no puede tener éxito. Se distingue por el texto
    porque comparte ``type`` con cualquier otro ``invalid_request_error``.
    """
    try:
        import anthropic
    except ImportError:  # pragma: no cover — el SDK siempre está en runtime
        return False
    if not isinstance(exc, anthropic.BadRequestError):
        return False
    texto = str(exc).lower()
    return any(m in texto for m in _CREDIT_MARKERS)


def _should_report_credit(clave: str, ahora: float) -> bool:
    """¿Toca abrir evento para ``clave``, o ya se reportó dentro de la ventana?"""
    with _lock:
        # Poda: sin esto el mapa crece con cada operación distinta que falle.
        for k, t in list(_last_credit_log.items()):
            if ahora - t > _CREDIT_LOG_WINDOW_SECONDS:
                del _last_credit_log[k]
        if ahora - _last_credit_log.get(clave, 0.0) > _CREDIT_LOG_WINDOW_SECONDS:
            _last_credit_log[clave] = ahora
            return True
    return False


def report_api_failure(logger: logging.Logger, exc: BaseException, *, label: str) -> None:
    """Reporta un fallo del API ya manejado (el llamador YA degrada a su fallback).

    Los fallos normales van a ``ERROR`` como siempre. El saldo agotado va a ``ERROR`` una
    vez por operación y por ventana, y a ``WARNING`` el resto de las veces.
    """
    if not is_credit_exhausted(exc):
        logger.error("Claude API error (%s): %s. Fallback estático.", label, exc)
        return

    caller = current_caller()
    clave = f"{caller.kind}:{caller.detail}"
    if _should_report_credit(clave, time.monotonic()):
        logger.error(
            "Crédito de Anthropic AGOTADO a nivel de organización — disparado por %s. "
            "Es un 400 determinista: no se resuelve reintentando ni rotando la clave, hay "
            "que reponer saldo. Toda narrativa IA degrada a estático mientras dure. "
            "Repeticiones de esta misma operación bajan a WARNING durante %d min. "
            "Detalle (%s): %s",
            clave, int(_CREDIT_LOG_WINDOW_SECONDS // 60), label, exc)
    else:
        logger.warning(
            "Crédito de Anthropic agotado (%s · %s): degradado a estático. Ya reportado "
            "para esta operación dentro de la ventana.", clave, label)
