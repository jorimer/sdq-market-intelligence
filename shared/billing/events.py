"""Eventos de billing: alerta a suscriptos ante un cambio de tarifa (monetización B2).

Al publicar una tarifa que **cambia** un precio actualmente vigente (no la primera fijación
de un SKU), ``create_tariff`` publica ``tariff.published`` en el event_bus. Acá se suscribe
el efecto: resolver la audiencia afectada (``affected_subscribers``) y persistirle una
notificación in-app con el precio nuevo y la fecha de vigencia.

Desacoplado como el resto (escucha eventos, abre su propia sesión); no acopla el publicador
a la entrega. Un fallo notificando NO debe romper la publicación de la tarifa.
"""
import logging
from datetime import datetime
from typing import Any, Dict

from shared.billing.skus import sku_label
from shared.billing.subscribers import affected_subscribers
from shared.database.session import SessionLocal
from shared.events.event_bus import event_bus
from shared.notifications.service import notification_service

logger = logging.getLogger("sdq.billing.events")

TARIFF_PUBLISHED = "tariff.published"


def _format_effective(iso: str) -> str:
    """Fecha de vigencia legible (YYYY-MM-DD) a partir del ISO del payload; best-effort."""
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except (ValueError, TypeError):
        return iso


def _on_tariff_published(payload: Dict[str, Any]) -> None:
    # Solo un cambio sobre un precio vigente alerta (la primera fijación de un SKU no).
    if not payload.get("is_change"):
        return
    sku = payload.get("sku", "")
    db = SessionLocal()
    try:
        users = affected_subscribers(db, sku)
        if not users:
            return
        label = sku_label(sku)
        currency = payload.get("currency", "")
        amount = payload.get("amount", "")
        when = _format_effective(payload.get("effective_from", ""))
        title = "Cambio de tarifa programado"
        body = (f"El precio de tu {label} pasará a {currency} {amount}, "
                f"vigente desde el {when}.")
        for user in users:
            notification_service.create(db, user_id=user.id, type="info",
                                        title=title, body=body, action_url="/mi-plan")
        logger.info("Alerta de tarifa '%s' enviada a %d suscriptos", sku, len(users))
    except Exception:  # noqa: BLE001 — notificar no debe romper la publicación de la tarifa
        logger.exception("Fallo al alertar el cambio de tarifa '%s'", sku)
        db.rollback()
    finally:
        db.close()


def subscribe_billing_events() -> None:
    """Suscribe la alerta de tarifa al event_bus. Idempotente a nivel de arranque."""
    event_bus.subscribe(TARIFF_PUBLISHED, _on_tariff_published)
    logger.info("billing suscrito a %s", TARIFF_PUBLISHED)
