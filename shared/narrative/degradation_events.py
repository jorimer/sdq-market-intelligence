"""Evento de ops para narrativa degradada a fallback estático.

Cuando el guard bloquea (o detecta) un reporte cuya narrativa IA cayó al relleno estático,
además del WARNING en el punto de decisión se emite un evento INTERNO al ``event_bus``
(``NARRATIVE_DEGRADED``). Eso da un punto de enganche formal y desacoplado para la métrica /
alerta de operación —hoy un suscriptor por defecto que loguea de forma estructurada; mañana
un sink real (StatsD, Slack, PagerDuty) se suscribe aquí sin tocar los choke points.

NO es un evento público: no está en ``shared.data_api.webhooks.PUBLIC_EVENTS``, así que el
despachador de webhooks de clientes nunca lo reenvía. La doctrina "NO se expone la narrativa
IA" se mantiene: esto es telemetría de operación, no dato de cliente.
"""
import logging
from typing import List, Optional

from shared.events.event_bus import NARRATIVE_DEGRADED, event_bus

logger = logging.getLogger("sdq.narrative.degradation")


def emit_narrative_degraded(
    *,
    surface: str,
    sector_key: str,
    tier: str,
    sections: List[str],
    blocked: bool,
    scope: Optional[str] = None,
    period: Optional[str] = None,
) -> None:
    """Publica ``NARRATIVE_DEGRADED`` con el contexto de la degradación.

    ``surface``: "products" (framework) | "banking_legacy". ``blocked``: True si la entrega se
    abortó (premium); False si solo se registró (Pulse abierto). Best-effort: un fallo al
    publicar NUNCA rompe la generación del reporte (el WARNING del choke point ya dejó rastro).
    """
    payload = {
        "surface": surface,
        "sector_key": sector_key,
        "tier": tier,
        "scope": scope,
        "period": period,
        "sections": list(sections),
        "section_count": len(sections),
        "blocked": blocked,
        # Causa indeterminada en el punto de detección (solo se ve el TEXTO): rate-limit/outage
        # del API o corte de presupuesto — el marcador static_fallback cubre ambas por igual.
        "cause": "transient_llm_degradation",
    }
    try:
        event_bus.publish(NARRATIVE_DEGRADED, payload)
    except Exception:  # noqa: BLE001 — la telemetría jamás debe tumbar la entrega
        logger.exception("No se pudo publicar NARRATIVE_DEGRADED (%s/%s)", sector_key, tier)


def _on_narrative_degraded(payload: dict) -> None:
    """Suscriptor de ops por defecto: deja un registro estructurado, más ruidoso si se bloqueó
    la entrega de un premium. Punto único para enganchar un sink de métricas/alertas real."""
    blocked = payload.get("blocked")
    msg = ("ALERTA narrativa degradada [%s] %s/%s scope=%s período=%s: %d sección(es) %s "
           "-> %s")
    args = (payload.get("surface"), payload.get("sector_key"), payload.get("tier"),
            payload.get("scope"), payload.get("period"), payload.get("section_count"),
            payload.get("sections"),
            "ENTREGA BLOQUEADA (premium)" if blocked else "registrado (nivel abierto)")
    (logger.error if blocked else logger.warning)(msg, *args)


def subscribe_narrative_degradation_events() -> None:
    """Engancha el suscriptor de ops por defecto. Se llama una vez, al arrancar la app."""
    event_bus.subscribe(NARRATIVE_DEGRADED, _on_narrative_degraded)
    logger.info("ops suscrito a %s", NARRATIVE_DEGRADED)
