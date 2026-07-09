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
from shared.billing.skus import deep_dive_sku, entitlement_for_sku

logger = logging.getLogger("sdq.billing.webhook")


class WebhookError(Exception):
    """Firma inválida o payload no verificable → rechazar (400)."""


def _already_processed(db: Session, provider: str, event_id: str) -> bool:
    return db.query(
        db.query(BillingEvent).filter_by(provider=provider, event_id=event_id).exists()
    ).scalar()


def _record_transaction(db: Session, provider: str, ev: NormalizedEvent, kind: str) -> None:
    """Persiste la transacción facturable (desglose subtotal + impuesto = total) del cobro.
    Desglose autoritativo desde el tarifario + país del cliente; si el precio ya no está en
    el tarifario (cambió tras el checkout), back-deriva del bruto que cobró el proveedor.
    Best-effort: un fallo al facturar NO revierte el acceso ya concedido."""
    from shared.auth.models import User
    from shared.billing.tariffs import price_for
    from shared.billing.tax import compute_tax, compute_tax_from_total
    from shared.billing.transactions import record_transaction
    from shared.settings.service import get_tax_config

    if not ev.user_id or not ev.sku:
        return
    try:
        user = db.query(User).filter_by(id=ev.user_id).one_or_none()
        country = getattr(user, "country", None) if user else None
        cfg = get_tax_config(db)
        interval = ev.interval or "once"
        row = price_for(db, ev.sku, interval)
        if row is not None:
            bd = compute_tax(row.amount, currency=row.currency, country=country, config=cfg)
        elif ev.amount_gross:
            bd = compute_tax_from_total(ev.amount_gross,
                                        currency=ev.amount_currency or "USD",
                                        country=country, config=cfg)
        else:
            logger.warning("[billing] sin precio ni bruto para facturar %s (%s)", ev.sku, kind)
            return
        record_transaction(db, user_id=ev.user_id, sku=ev.sku, kind=kind, provider=provider,
                            provider_ref=ev.provider_ref, event_id=ev.event_id,
                            breakdown=bd, note="PayPal")
    except Exception:  # noqa: BLE001 — facturar no debe tumbar la concesión de acceso
        logger.exception("[billing] no se pudo registrar la transacción de %s", ev.sku)


def _apply(db: Session, provider: str, ev: NormalizedEvent) -> str:
    """Aplica un evento normalizado. Devuelve una etiqueta de lo hecho."""
    from shared.products.entitlements import grant_entitlement
    from shared.products.subscriptions import apply_subscription, expire_subscription

    if ev.kind == "order_paid":
        if not ev.user_id or not ev.sku:
            return "order_sin_datos"
        ent = entitlement_for_sku(ev.sku)  # (sector, ProductTier.deep_dive) o None
        if ent is None:
            return "order_sku_no_entitlement"
        grant_entitlement(db, user_id=ev.user_id, sector_key=ent[0], tier=ent[1].value,
                          granted_by=None, source="order",
                          note=f"PayPal {ev.provider_ref}")
        _record_transaction(db, provider, ev, "order")
        return "entitlement_otorgado"

    if ev.kind == "subscription_active":
        if not ev.user_id or not ev.sku:
            return "sub_sin_datos"
        from shared.products.subscriptions import tier_for_sku
        period_end = None
        if ev.period_end:
            try:
                period_end = datetime.fromisoformat(ev.period_end.replace("Z", "+00:00"))
            except ValueError:
                period_end = None
        apply_subscription(db, user_id=ev.user_id, provider=provider,
                           provider_subscription_id=ev.provider_ref, sku=ev.sku,
                           interval=ev.interval,
                           tier=tier_for_sku(ev.sku).value, status="active",
                           current_period_end=period_end, note="PayPal")
        _record_transaction(db, provider, ev, "subscription")
        return "suscripcion_activa"

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
    provider = get_provider(db, provider_name)
    if not provider.is_configured():
        return {"status": "ignored", "reason": "provider_not_configured"}
    if not provider.verify_webhook(headers=headers, body=body):
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
