"""Webhooks de "hay dato nuevo" — el cliente deja de sondear.

Qué resuelve: sin aviso, un consumidor que quiere estar al día tiene que preguntar cada
hora si el BCRD publicó algo. Es caro para él, ruidoso para nosotros, y aun así llega
tarde. Con aviso, PMS refresca cuando el snapshot se recalcula.

Tres decisiones que definen el diseño:

1. **El aviso no lleva el dato.** Solo dice qué cambió (evento, sector, período). El
   cliente vuelve por la API con su llave. Si el payload trajera el dato, el webhook
   sería un segundo canal de acceso —con su propia superficie de permisos y su propia
   forma de filtrarse— y ya tenemos uno bien gobernado.
2. **Se firma cada envío (HMAC-SHA256).** Una URL de webhook es pública por naturaleza:
   sin firma, cualquiera que la adivine puede inyectar avisos falsos y hacer que el
   cliente recalcule con basura.
3. **Es best-effort y no bloquea.** La entrega corre en un hilo aparte: si el endpoint
   del cliente está caído o lento, el sync que originó el evento no puede quedarse
   esperando. Tras varios fallos seguidos el webhook se desactiva solo.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from shared.data_api.models import ApiKey, ApiWebhook, ApiWebhookDelivery

logger = logging.getLogger("sdq.data_api.webhooks")

# Eventos del bus interno que se reexponen como aviso al cliente. La lista es explícita
# a propósito: no todo evento interno es asunto de un tercero.
PUBLIC_EVENTS = (
    "macro.updated",
    "irmp.updated",
    "esg.updated",
    "trade.updated",
    "sector.updated",
    "energy.updated",
    "telecom.updated",
    "tourism.updated",
    "construction.updated",
    "free_zones.updated",
)

MAX_CONSECUTIVE_FAILURES = 10
TIMEOUT_SECONDS = 10.0
SIGNATURE_HEADER = "X-SDQ-Signature"
EVENT_HEADER = "X-SDQ-Event"


def sign_payload(secret: str, body: bytes) -> str:
    """Firma del cuerpo: ``sha256=<hex>``. El receptor recomputa y compara."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Verificación en tiempo constante — para el SDK del cliente y para los tests."""
    return hmac.compare_digest(sign_payload(secret, body), signature or "")


def _subscribed(hook: ApiWebhook, event: str) -> bool:
    wanted = {e.strip() for e in str(hook.events or "").split(",") if e.strip()}
    return "*" in wanted or event in wanted


def _deliver(db_factory, hook_id: str, event: str, payload: Dict[str, Any]) -> None:
    """Un intento de entrega, con su propia sesión (corre fuera del request)."""
    db: Session = db_factory()
    try:
        hook = db.query(ApiWebhook).filter(ApiWebhook.id == hook_id).one_or_none()
        if hook is None or not hook.active:
            return
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: event,
            SIGNATURE_HEADER: sign_payload(str(hook.secret), body),
            "User-Agent": "SDQ-Data-API-Webhook/1",
        }
        status_code: Optional[int] = None
        error: Optional[str] = None
        try:
            resp = httpx.post(str(hook.url), content=body, headers=headers,
                              timeout=TIMEOUT_SECONDS)
            status_code = resp.status_code
            ok = 200 <= resp.status_code < 300
        except Exception as exc:  # noqa: BLE001 — red del cliente, no nuestra
            error = f"{type(exc).__name__}: {exc}"[:255]
            ok = False

        hook.last_delivery_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if ok:
            hook.consecutive_failures = 0
        else:
            hook.consecutive_failures = int(hook.consecutive_failures or 0) + 1
            if hook.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                # Se desactiva solo: un endpoint muerto no debe costar un intento por
                # evento para siempre. Reactivarlo es explícito (el dueño lo re-registra).
                hook.active = False
                logger.warning(
                    "data_api: webhook %s desactivado tras %d fallos seguidos",
                    hook_id, hook.consecutive_failures,
                )
        db.add(ApiWebhookDelivery(
            webhook_id=hook_id, event=event, status_code=status_code, error=error,
            attempted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_api: entrega de webhook %s falló: %s", hook_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def dispatch(event: str, payload: Dict[str, Any], *, db_factory=None,
             background: bool = True) -> int:
    """Avisa a los webhooks suscritos a *event*. Devuelve cuántos se despacharon.

    ``background=False`` entrega en línea — solo para tests: en producción el sync que
    disparó el evento no puede quedarse esperando la red del cliente.
    """
    if db_factory is None:
        from shared.database.session import SessionLocal

        db_factory = SessionLocal

    db: Session = db_factory()
    try:
        hooks: List[ApiWebhook] = (
            db.query(ApiWebhook).filter(ApiWebhook.active.is_(True)).all()
        )
        targets = [h for h in hooks if _subscribed(h, event)]
        # La llave dueña debe seguir viva: revocarla corta también los avisos, sin que
        # nadie tenga que acordarse de borrar el webhook.
        live: List[str] = []
        for h in targets:
            key = db.query(ApiKey).filter(ApiKey.id == h.api_key_id).one_or_none()
            if key is not None and key.active and key.revoked_at is None:
                live.append(str(h.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_api: no se pudo resolver los webhooks de '%s': %s", event, exc)
        return 0
    finally:
        db.close()

    body = {
        "event": event,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        # El aviso NO trae el dato: dice qué mirar, el cliente lo pide con su llave.
        "summary": {k: v for k, v in (payload or {}).items()
                    if k in ("period", "sector_key", "series_count", "signal_count",
                             "scored", "countries")},
        "hint": "Consulte /api/data/v1/catalog/changes y los recursos afectados.",
    }
    for hook_id in live:
        if background:
            threading.Thread(
                target=_deliver, args=(db_factory, hook_id, event, body), daemon=True,
            ).start()
        else:
            _deliver(db_factory, hook_id, event, body)
    return len(live)


def subscribe_webhook_events() -> None:
    """Engancha el despachador al bus interno. Se llama una vez, al arrancar la app."""
    from shared.events.event_bus import event_bus

    for event in PUBLIC_EVENTS:
        event_bus.subscribe(
            event,
            lambda payload, _e=event: dispatch(_e, payload or {}),
        )
    logger.info("data_api: webhooks suscritos a %d eventos públicos", len(PUBLIC_EVENTS))
