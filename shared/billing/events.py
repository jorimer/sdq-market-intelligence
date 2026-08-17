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

from shared.auth.models import User
from shared.billing.skus import sku_label
from shared.billing.subscribers import affected_subscribers
from shared.database.session import SessionLocal
from shared.events.event_bus import event_bus
from shared.notifications.service import notification_service

logger = logging.getLogger("sdq.billing.events")

TARIFF_PUBLISHED = "tariff.published"
# La secuencia fiscal está por agotarse (o ya se agotó) al emitir un comprobante. Se avisa
# ANTES de que un cobro se quede sin número, que es cuando todavía se puede pedir el rango.
FISCAL_SEQUENCE_LOW = "fiscal.sequence.low"
# Se cobró algo que la plataforma NO entrega sola (``special:{slug}``: un informe a medida).
# Sin este aviso el cliente paga y nadie se entera de que hay que producirlo.
ORDER_NEEDS_FULFILMENT = "order.needs_fulfilment"


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


def _fiscal_admins(db) -> list:
    """A quién se le avisa que la numeración fiscal se está acabando: a quien puede pedir el
    rango a la DGII y cargarlo — los administradores activos."""
    from shared.auth.models import ROLE_RANK, User, UserRole

    minimum = ROLE_RANK[UserRole.admin]
    return [u for u in db.query(User).filter(User.is_active.is_(True)).all()
            if ROLE_RANK.get(u.role, 0) >= minimum]


def _on_fiscal_sequence_low(payload: Dict[str, Any]) -> None:
    """Avisa a los admins que un rango de comprobantes está por agotarse o ya se agotó.

    El caso AGOTADO es el grave y se nombra como tal: el cobro se registró **sin número
    fiscal**, así que hay una venta esperando su comprobante. No se rellena con nada — se
    declara y se asigna retroactivamente al cargar el rango."""
    from shared.billing.fiscal.types import doc_label

    db = SessionLocal()
    try:
        regime = payload.get("regime", "")
        doc_type = payload.get("doc_type", "")
        try:
            label = doc_label(regime, doc_type)
        except ValueError:
            label = "Comprobante fiscal"
        exhausted = bool(payload.get("exhausted"))
        remaining = payload.get("remaining")
        if exhausted:
            title = "Sin comprobantes fiscales disponibles"
            body = (f"Se registró un cobro SIN número fiscal: no queda rango de «{label}» "
                    f"({doc_type}). Cargá el rango autorizado por la DGII y asigná los "
                    "comprobantes pendientes.")
            kind = "error"
        else:
            title = "La secuencia fiscal se está agotando"
            body = (f"Quedan {remaining} comprobantes de «{label}» ({doc_type}). Solicitá el "
                    "próximo rango a la DGII antes de que se acabe.")
            kind = "warning"
        for user in _fiscal_admins(db):
            notification_service.create(db, user_id=user.id, type=kind, title=title,
                                        body=body, action_url="/admin/ncf")
        logger.info("Aviso de secuencia fiscal %s/%s (agotada=%s, quedan=%s)",
                    regime, doc_type, exhausted, remaining)
    except Exception:  # noqa: BLE001 — avisar no debe romper la facturación
        logger.exception("Fallo al avisar el estado de la secuencia fiscal")
        db.rollback()
    finally:
        db.close()


def _on_order_needs_fulfilment(payload: Dict[str, Any]) -> None:
    """Avisa a los admins que hay una compra cobrada que hay que ENTREGAR A MANO.

    Aplica a los ``special:{slug}`` (informes cotizados a medida): la plataforma cobra y
    factura, pero no tiene qué conceder — el trabajo lo hace una persona."""
    db = SessionLocal()
    try:
        sku = payload.get("sku", "")
        cliente = db.query(User).filter_by(id=payload.get("user_id")).one_or_none() \
            if payload.get("user_id") else None
        quien = getattr(cliente, "email", None) or "un cliente"
        for user in _fiscal_admins(db):
            notification_service.create(
                db, user_id=user.id, type="warning",
                title="Compra que requiere entrega manual",
                body=(f"{quien} pagó «{sku_label(sku)}». La plataforma cobró y facturó, pero "
                      "este producto no se entrega solo: hay que producirlo y enviarlo. "
                      f"Referencia de PayPal: {payload.get('order_id', '—')}."),
                action_url="/admin/comprobantes")
        logger.info("Aviso de entrega manual para '%s'", sku)
    except Exception:  # noqa: BLE001 — avisar no debe romper la liquidación
        logger.exception("Fallo al avisar la entrega manual")
        db.rollback()
    finally:
        db.close()


def subscribe_billing_events() -> None:
    """Suscribe las alertas de billing al event_bus. Idempotente a nivel de arranque."""
    event_bus.subscribe(TARIFF_PUBLISHED, _on_tariff_published)
    event_bus.subscribe(FISCAL_SEQUENCE_LOW, _on_fiscal_sequence_low)
    event_bus.subscribe(ORDER_NEEDS_FULFILMENT, _on_order_needs_fulfilment)
    logger.info("billing suscrito a %s, %s, %s", TARIFF_PUBLISHED, FISCAL_SEQUENCE_LOW,
                ORDER_NEEDS_FULFILMENT)
