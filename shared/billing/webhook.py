"""Despacho de webhooks de la pasarela → modelo de acceso (Fase 3).

Verifica la firma con el proveedor, DEDUPLICA por ``event_id`` (idempotencia) y aplica el
evento normalizado al eje de acceso ya existente: ``grant_entitlement`` (compra puntual),
``apply_subscription`` / ``expire_subscription`` (suscripción). No muta ``User.tier``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.billing.models import BillingEvent
from shared.billing.providers import get_provider
from shared.billing.providers.base import NormalizedEvent
from shared.billing.skus import deep_dive_sku

logger = logging.getLogger("sdq.billing.webhook")


class WebhookError(Exception):
    """Firma inválida o payload no verificable → rechazar (400)."""


def _already_processed(db: Session, provider: str, event_id: str) -> bool:
    return db.query(
        db.query(BillingEvent).filter_by(provider=provider, event_id=event_id).exists()
    ).scalar()


def _apply(db: Session, provider: str, ev: NormalizedEvent) -> str:
    """Aplica un evento normalizado. Devuelve una etiqueta de lo hecho. Reusa la MISMA
    liquidación que el retorno/captura (``shared/billing/settlement.py``): concede el acceso +
    factura de forma idempotente, así el webhook (en vivo) reconcilia sin duplicar lo que el
    retorno ya concedió (en sandbox, donde puede no haber webhook)."""
    from shared.billing.settlement import (
        settle_order,
        settle_refund,
        settle_renewal,
        settle_subscription,
    )
    from shared.products.subscriptions import apply_subscription, expire_subscription

    if ev.kind == "order_paid":
        return settle_order(db, provider, order_id=ev.provider_ref, user_id=ev.user_id,
                            sku=ev.sku, gross=ev.amount_gross, currency=ev.amount_currency)

    if ev.kind == "subscription_active":
        return settle_subscription(db, provider, subscription_id=ev.provider_ref,
                                   user_id=ev.user_id, sku=ev.sku, interval=ev.interval,
                                   period_end=ev.period_end, gross=ev.amount_gross,
                                   currency=ev.amount_currency, charge_ref=ev.charge_ref)

    # Cobro recurrente: extiende el período (si no, el acceso se corta al mes 2 mientras
    # PayPal sigue cobrando) y factura ESE cobro con su propio comprobante.
    if ev.kind == "subscription_renewed":
        return settle_renewal(db, provider, subscription_id=ev.provider_ref,
                              charge_ref=ev.charge_ref or ev.event_id,
                              gross=ev.amount_gross, currency=ev.amount_currency,
                              user_id=ev.user_id, sku=ev.sku)

    if ev.kind == "payment_refunded":
        return settle_refund(db, provider, charge_ref=ev.provider_ref,
                             refund_ref=ev.charge_ref or ev.event_id,
                             gross=ev.amount_gross, currency=ev.amount_currency)

    if ev.kind in ("subscription_cancelled", "subscription_expired"):
        status = "cancelled" if ev.kind == "subscription_cancelled" else "expired"
        if ev.user_id and ev.sku:
            from shared.products.subscriptions import tier_for_sku
            apply_subscription(db, user_id=ev.user_id, provider=provider,
                               provider_subscription_id=ev.provider_ref, sku=ev.sku,
                               tier=tier_for_sku(ev.sku).value, status=status)
        else:  # sin custom_id: al menos cortar por id de proveedor
            expire_subscription(db, provider, ev.provider_ref)
        return f"suscripcion_{status}"

    return "ignorado"


def handle_webhook(db: Session, provider_name: str, headers: Dict[str, str], body: bytes) -> Dict[str, Any]:
    """Procesa un webhook: verifica firma, deduplica y aplica. Idempotente."""
    from shared.billing.providers.base import ProviderNotConfigured

    provider = get_provider(db, provider_name)
    if not provider.is_configured():
        return {"status": "ignored", "reason": "provider_not_configured"}
    try:
        verified = provider.verify_webhook(headers=headers, body=body)
    except ProviderNotConfigured as e:
        # Falta el webhook_id. Se distingue de "firma inválida" a propósito: el síntoma es el
        # mismo (el evento no se aplica) pero la causa y el arreglo no.
        logger.error("[billing] webhook %s NO verificable: %s", provider_name, e)
        return {"status": "ignored", "reason": "webhook_not_configured", "detail": str(e)}
    if not verified:
        raise WebhookError("Firma de webhook inválida.")
    try:
        payload = json.loads(body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        raise WebhookError("Payload de webhook ilegible.")

    ev = provider.parse_event(payload)
    if ev is None or not ev.event_id:
        return {"status": "ignored", "reason": "event_not_relevant"}
    if _already_processed(db, provider_name, ev.event_id):
        return {"status": "duplicate", "event_id": ev.event_id}

    result = _apply(db, provider_name, ev)
    # Registrar el evento como procesado (idempotencia). La unicidad cierra la carrera
    # entre dos entregas concurrentes del mismo evento.
    db.add(BillingEvent(provider=provider_name, event_id=ev.event_id, kind=ev.kind,
                        processed_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "event_id": ev.event_id}
    logger.info("[billing] webhook %s %s → %s", provider_name, ev.kind, result)
    return {"status": "applied", "kind": ev.kind, "result": result}


# ``deep_dive_sku`` re-export para conveniencia de los checkout endpoints.
__all__ = ["handle_webhook", "WebhookError", "deep_dive_sku"]
