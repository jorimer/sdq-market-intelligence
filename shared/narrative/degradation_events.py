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
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from shared.events.event_bus import NARRATIVE_DEGRADED, event_bus

logger = logging.getLogger("sdq.narrative.degradation")

# Un solo registro de incidente por VENTANA: durante un outage se acumulan muchas entregas
# bloqueadas; en vez de una fila por intento, se agrupan en una sola fila de la Consola de
# Operaciones cuyo `finished_at` (última ocurrencia) se va refrescando y cuyo `summary.count`
# se incrementa. Ventana deslizante: si sigue degradando dentro del día, sigue en la misma
# fila; un hueco > 24h abre una fila nueva.
_INCIDENT_OP = "narrative-degraded"
_INCIDENT_WINDOW_SECONDS = 86400


def _naive_utc_now() -> datetime:
    """UTC naive, igual que ``operations.service._dt`` (columnas DateTime sin tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _incident_error(count: int, target: str, section_count) -> str:
    if count <= 1:
        return (f"1 degradación de narrativa — {target}, {section_count} sección(es) de "
                f"análisis, entrega premium bloqueada.")
    return (f"{count} degradaciones de narrativa en las últimas 24h "
            f"(última: {target}, {section_count} sección(es)). Entregas premium bloqueadas.")


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
    # Solo las degradaciones que BLOQUEAN una entrega premium se anotan en el historial de la
    # Consola de Operaciones (que ve el admin/superadmin). Las de nivel abierto (Pulse) quedan
    # solo en log para no inundar el feed. Best-effort: un fallo de persistencia no rompe nada.
    if blocked:
        _record_ops_incident(payload)


def _record_ops_incident(payload: dict) -> None:
    """Anota la degradación bloqueada en la Consola de Operaciones, AGRUPADA por ventana.

    Si ya hay una fila ``narrative-degraded`` con ``finished_at`` dentro de la ventana, la
    ACTUALIZA (incrementa ``count``, refresca ``last_at``/``finished_at``, acumula ``by_target``);
    si no, crea una nueva. Sesión propia (el evento se publica en el hilo del request, con su
    sesión ocupada); nunca propaga excepción. Nota: sin bloqueo entre requests concurrentes un
    outage puede crear alguna fila extra ocasional — aceptable para telemetría."""
    try:
        from shared.database.session import SessionLocal
        from shared.operations.models import OperationRun
        from shared.operations.service import record_incident
    except Exception:  # noqa: BLE001 — sin ops/DB (tests aislados) no hay historial que escribir
        return
    db = SessionLocal()
    try:
        now = _naive_utc_now()
        cutoff = now - timedelta(seconds=_INCIDENT_WINDOW_SECONDS)
        target = f"{payload.get('sector_key')}/{payload.get('tier')}"
        detail = {k: payload.get(k) for k in
                  ("surface", "sector_key", "tier", "scope", "period",
                   "sections", "section_count", "cause")}
        section_count = payload.get("section_count")
        row = (db.query(OperationRun)
               .filter(OperationRun.operation == _INCIDENT_OP,
                       OperationRun.finished_at.isnot(None),
                       OperationRun.finished_at >= cutoff)
               .order_by(OperationRun.finished_at.desc())
               .first())
        if row is None:  # nueva ventana → fila nueva (count=1)
            record_incident(
                db, _INCIDENT_OP,
                summary={"count": 1, "window_seconds": _INCIDENT_WINDOW_SECONDS,
                         "first_at": now.isoformat(), "last_at": now.isoformat(),
                         "by_target": {target: 1}, "last": detail},
                error=_incident_error(1, target, section_count))
            return
        summ = dict(row.summary or {})
        count = int(summ.get("count", 1)) + 1
        by = dict(summ.get("by_target") or {})
        by[target] = int(by.get(target, 0)) + 1
        summ.update(count=count, last_at=now.isoformat(), by_target=by, last=detail)
        summ.setdefault("window_seconds", _INCIDENT_WINDOW_SECONDS)
        summ.setdefault("first_at", (row.started_at or now).isoformat())
        row.summary = summ                       # reasignar dict → SQLAlchemy marca dirty
        row.finished_at = now
        row.error = _incident_error(count, target, section_count)
        db.commit()
    except Exception:  # noqa: BLE001 — la telemetría jamás debe tumbar la entrega
        db.rollback()
        logger.exception("No se pudo registrar el incidente de narrativa degradada en ops")
    finally:
        db.close()


def subscribe_narrative_degradation_events() -> None:
    """Engancha el suscriptor de ops por defecto. Se llama una vez, al arrancar la app."""
    event_bus.subscribe(NARRATIVE_DEGRADED, _on_narrative_degraded)
    logger.info("ops suscrito a %s", NARRATIVE_DEGRADED)
