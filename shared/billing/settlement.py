"""Liquidación de un pago → acceso + factura (monetización Fase 4).

Punto ÚNICO donde un pago confirmado se convierte en acceso concedido + transacción
facturable. Lo llaman DOS caminos que convergen de forma idempotente:

- **Retorno/captura** (``/checkout/order/capture`` y ``/checkout/subscription/activate``):
  concede el acceso en el momento en que el cliente vuelve de PayPal. Es el camino que hace
  funcionar el flujo **sin webhook** (p.ej. el sandbox de PayPal, donde no siempre se puede
  configurar un webhook).
- **Webhook** (``PAYMENT.CAPTURE.COMPLETED`` / ``BILLING.SUBSCRIPTION.ACTIVATED``): en vivo
  reconcilia lo mismo. NO duplica: la transacción usa un ``event_id`` DETERMINISTA por
  ``provider_ref`` (``settle:order:{ref}`` / ``settle:sub:{ref}``), así el índice único
  ``(provider, event_id)`` deja pasar una sola factura, y el acceso se concede solo cuando la
  transacción se creó de verdad (``created``). El upsert de suscripción ya es idempotente por
  su id de proveedor.

El desglose fiscal es autoritativo desde el tarifario + país del cliente; si el precio ya no
está en el tarifario (cambió tras el checkout), se back-deriva del bruto que cobró PayPal.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.billing.settlement")


def _breakdown_for(db: Session, *, sku: str, interval: str, country: Optional[str],
                   gross: Optional[str], gross_currency: Optional[str]):
    """Desglose desde el tarifario (autoritativo); si no hay precio, back-deriva del bruto."""
    from shared.billing.tariffs import price_for
    from shared.billing.tax import compute_tax, compute_tax_from_total
    from shared.settings.service import get_tax_config

    cfg = get_tax_config(db)
    row = price_for(db, sku, interval)
    if row is not None:
        return compute_tax(row.amount, currency=row.currency, country=country, config=cfg)
    if gross:
        return compute_tax_from_total(gross, currency=gross_currency or "USD",
                                      country=country, config=cfg)
    return None


def _client_country(db: Session, user_id: str) -> Optional[str]:
    from shared.auth.models import User

    user = db.query(User).filter_by(id=user_id).one_or_none()
    return getattr(user, "country", None) if user else None


def _record_invoice_best_effort(db: Session, *, provider: str, kind: str, provider_ref: str,
                                user_id: str, sku: str, interval: str, gross: Optional[str],
                                currency: Optional[str]) -> None:
    """Registra la factura del cobro. Best-effort: **facturar nunca tumba el acceso ya
    concedido**. Idempotente por ``event_id`` determinista (webhook y retorno convergen)."""
    from shared.billing.transactions import record_transaction_once

    try:
        country = _client_country(db, user_id)
        bd = _breakdown_for(db, sku=sku, interval=interval, country=country,
                            gross=gross, gross_currency=currency)
        if bd is None:
            logger.warning("[billing] sin precio ni bruto para facturar %s (%s)", sku, provider_ref)
            return
        record_transaction_once(db, user_id=user_id, sku=sku, kind=kind, provider=provider,
                                provider_ref=provider_ref, event_id=f"settle:{kind}:{provider_ref}",
                                breakdown=bd, note="PayPal")
    except Exception:  # noqa: BLE001 — facturar no debe revertir la concesión de acceso
        db.rollback()
        logger.exception("[billing] no se pudo registrar la factura de %s", sku)


def settle_order(db: Session, provider: str, *, order_id: str, user_id: Optional[str],
                 sku: Optional[str], gross: Optional[str] = None,
                 currency: Optional[str] = None) -> str:
    """Concede el Deep Dive comprado (idempotente por ``order_id``, así el retorno/captura y el
    webhook no duplican) y registra la factura best-effort. Devuelve una etiqueta de lo hecho."""
    from shared.billing.skus import entitlement_for_sku
    from shared.products.entitlements import grant_entitlement, order_entitlement_exists

    if not user_id or not sku:
        return "order_sin_datos"
    ent = entitlement_for_sku(sku)  # (sector, ProductTier.deep_dive) o None
    if ent is None:
        return "order_sku_no_entitlement"

    note = f"PayPal {order_id}"
    if order_entitlement_exists(db, user_id=user_id, sector_key=ent[0], tier=ent[1].value, note=note):
        label = "orden_ya_liquidada"
    else:
        grant_entitlement(db, user_id=user_id, sector_key=ent[0], tier=ent[1].value,
                          granted_by=None, source="order", note=note)
        label = "entitlement_otorgado"
    _record_invoice_best_effort(db, provider=provider, kind="order", provider_ref=order_id,
                                user_id=user_id, sku=sku, interval="once",
                                gross=gross, currency=currency)
    return label


def settle_subscription(db: Session, provider: str, *, subscription_id: str,
                        user_id: Optional[str], sku: Optional[str],
                        interval: Optional[str] = None, period_end: Optional[str] = None,
                        gross: Optional[str] = None, currency: Optional[str] = None) -> str:
    """Activa/renueva la suscripción y registra la factura. El upsert por id de proveedor ya es
    idempotente; la factura no se duplica (event_id determinista)."""
    from shared.products.subscriptions import apply_subscription, tier_for_sku

    if not user_id or not sku:
        return "sub_sin_datos"
    pe: Optional[datetime] = None
    if period_end:
        try:
            pe = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
        except ValueError:
            pe = None
    # Upsert idempotente por id de proveedor (retorno y webhook no duplican).
    apply_subscription(db, user_id=user_id, provider=provider,
                       provider_subscription_id=subscription_id, sku=sku, interval=interval,
                       tier=tier_for_sku(sku).value, status="active",
                       current_period_end=pe, note="PayPal")
    _record_invoice_best_effort(db, provider=provider, kind="subscription",
                                provider_ref=subscription_id, user_id=user_id, sku=sku,
                                interval=interval or "monthly", gross=gross, currency=currency)
    return "suscripcion_activa"
