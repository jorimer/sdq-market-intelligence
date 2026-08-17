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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

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


def _client_fiscal(db: Session, user_id: str) -> tuple:
    """(país, tax_id) del cliente — definen el trato fiscal y el tipo de e-CF."""
    from shared.auth.models import User

    user = db.query(User).filter_by(id=user_id).one_or_none()
    if not user:
        return None, None
    return getattr(user, "country", None), getattr(user, "tax_id", None)


def _record_invoice_best_effort(db: Session, *, provider: str, kind: str, provider_ref: str,
                                user_id: str, sku: str, interval: str, gross: Optional[str],
                                currency: Optional[str],
                                charge_ref: Optional[str] = None) -> None:
    """Registra la factura del cobro. Best-effort: **facturar nunca tumba el acceso ya
    concedido**. Idempotente por ``event_id`` determinista (webhook y retorno convergen).

    ``charge_ref`` identifica el COBRO cuando hay varios sobre la misma referencia — el caso
    de las renovaciones: sin él, el cobro del mes 2 comparte ``event_id`` con el del mes 1 y
    la idempotencia lo descarta como duplicado, dejando la renovación sin factura ni NCF."""
    from shared.billing.transactions import record_transaction_once

    try:
        country, tax_id = _client_fiscal(db, user_id)
        bd = _breakdown_for(db, sku=sku, interval=interval, country=country,
                            gross=gross, gross_currency=currency)
        if bd is None:
            logger.warning("[billing] sin precio ni bruto para facturar %s (%s)", sku, provider_ref)
            return
        # El tipo de comprobante sale de la matriz fiscal: exento→exportación; RD con
        # RNC/cédula→crédito fiscal; RD sin→consumo. Lo resuelve ``record_transaction_once``
        # en los códigos del régimen ACTIVO, y ahí mismo consume el correlativo autorizado.
        event_id = f"settle:{kind}:{charge_ref or provider_ref}"
        record_transaction_once(db, user_id=user_id, sku=sku, kind=kind, provider=provider,
                                provider_ref=provider_ref, event_id=event_id,
                                breakdown=bd, note="PayPal",
                                client_has_rnc=bool((tax_id or "").strip()))
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

    # El SKU puede no mapear a ningún entitlement automático (``special:{slug}`` — un informe
    # cotizado a medida, que se entrega a mano). Eso NO puede saltearse la factura: antes se
    # devolvía acá y el cliente pagaba sin comprobante, sin NCF y sin registro contable.
    ent = entitlement_for_sku(sku)  # (sector, ProductTier.deep_dive) o None
    if ent is None:
        label = "orden_sin_entitlement_automatico"
        _notify_manual_fulfilment(db, user_id=user_id, sku=sku, order_id=order_id)
    else:
        note = f"PayPal {order_id}"
        if order_entitlement_exists(db, user_id=user_id, sector_key=ent[0],
                                    tier=ent[1].value, note=note):
            label = "orden_ya_liquidada"
        else:
            grant_entitlement(db, user_id=user_id, sector_key=ent[0], tier=ent[1].value,
                              granted_by=None, source="order", note=note)
            label = "entitlement_otorgado"

    _record_invoice_best_effort(db, provider=provider, kind="order", provider_ref=order_id,
                                user_id=user_id, sku=sku, interval="once",
                                gross=gross, currency=currency)
    return label


def _notify_manual_fulfilment(db: Session, *, user_id: str, sku: str, order_id: str) -> None:
    """Avisa a los administradores que se cobró algo que la plataforma NO entrega sola.

    Un ``special:{slug}`` es un informe a medida: sin este aviso, el cliente paga y nadie se
    entera de que hay que producirlo. Best-effort — avisar no puede tumbar la liquidación."""
    from shared.billing.events import ORDER_NEEDS_FULFILMENT
    from shared.events.event_bus import event_bus

    try:
        event_bus.publish(ORDER_NEEDS_FULFILMENT,
                          {"user_id": user_id, "sku": sku, "order_id": order_id})
    except Exception:  # noqa: BLE001
        logger.exception("[billing] no se pudo avisar la entrega manual de %s", sku)


def settle_subscription(db: Session, provider: str, *, subscription_id: str,
                        user_id: Optional[str], sku: Optional[str],
                        interval: Optional[str] = None, period_end: Optional[str] = None,
                        gross: Optional[str] = None, currency: Optional[str] = None,
                        charge_ref: Optional[str] = None) -> str:
    """Activa/renueva la suscripción y registra la factura. El upsert por id de proveedor ya es
    idempotente; la factura no se duplica (event_id determinista por ``charge_ref``)."""
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
                                interval=interval or "monthly", gross=gross, currency=currency,
                                charge_ref=charge_ref)
    return "suscripcion_activa"


def _period_end_for_renewal(db: Session, provider: str, subscription_id: str,
                            interval: Optional[str]) -> tuple:
    """Hasta cuándo llega el acceso tras un cobro recurrente, y de dónde salió el dato.

    Se pregunta a PayPal (autoritativo: ``next_billing_time``). Si esa llamada falla, se
    DERIVA del intervalo del plan y se declara así en el log — porque la alternativa es dejar
    sin acceso a alguien a quien se le acaba de cobrar, que es peor que una fecha inferida."""
    from shared.billing.providers import ProviderError, get_provider

    try:
        sub = get_provider(db, provider).get_subscription(subscription_id)
        nbt = (sub or {}).get("period_end")
        if nbt:
            return nbt, "paypal"
        interval = interval or (sub or {}).get("interval")
    except (ProviderError, Exception) as e:  # noqa: BLE001 — cualquier fallo cae al derivado
        logger.warning("[billing] no se pudo leer el período de %s en PayPal (%s); "
                       "se deriva del intervalo", subscription_id, e)

    days = 365 if (interval or "monthly") == "annual" else 31
    derived = datetime.now(timezone.utc) + timedelta(days=days)
    logger.info("[billing] período de %s DERIVADO del intervalo '%s' → %s",
                subscription_id, interval or "monthly", derived.date().isoformat())
    return derived.isoformat(), "derivado"


def settle_renewal(db: Session, provider: str, *, subscription_id: str,
                   charge_ref: str, gross: Optional[str] = None,
                   currency: Optional[str] = None, user_id: Optional[str] = None,
                   sku: Optional[str] = None) -> str:
    """Liquida un COBRO RECURRENTE: extiende el período y factura ese cobro con su propio
    comprobante.

    El evento de PayPal (``PAYMENT.SALE.COMPLETED``) casi nunca trae el ``custom_id``, así que
    el titular y el SKU se resuelven por la SUSCRIPCIÓN local, que es donde el alta los dejó.
    Sin suscripción local no se inventa nada: se registra y se sale."""
    from shared.products.models import Subscription

    row = (db.query(Subscription)
           .filter_by(provider=provider, provider_subscription_id=subscription_id)
           .one_or_none())
    titular = user_id or (str(row.user_id) if row is not None else None)
    producto = sku or (str(row.sku) if row is not None and row.sku else None)
    if not titular or not producto:
        logger.warning("[billing] cobro recurrente de una suscripción desconocida: %s",
                       subscription_id)
        return "renovacion_sin_suscripcion"

    interval = str(row.interval) if (row is not None and row.interval) else None
    period_end, origen = _period_end_for_renewal(db, provider, subscription_id, interval)

    settle_subscription(db, provider, subscription_id=subscription_id, user_id=titular,
                        sku=producto, interval=interval, period_end=period_end,
                        gross=gross, currency=currency, charge_ref=charge_ref)
    return f"renovacion_aplicada:{origen}"


def settle_refund(db: Session, provider: str, *, charge_ref: str,
                  refund_ref: str, gross: Optional[str] = None,
                  currency: Optional[str] = None) -> str:
    """Revierte un cobro reembolsado: marca la factura, corta el acceso que había concedido y
    emite la NOTA DE CRÉDITO que el régimen fiscal exige.

    Idempotente por el estado de la transacción original: un reembolso reentregado no emite
    una segunda nota de crédito."""
    from shared.billing.fiscal.credit_notes import issue_credit_note
    from shared.billing.models import BillingTransaction

    tx = (db.query(BillingTransaction)
          .filter_by(provider=provider, provider_ref=charge_ref)
          .order_by(BillingTransaction.created_at.asc())
          .first())
    if tx is None:
        logger.warning("[billing] reembolso de un cobro que no está facturado: %s", charge_ref)
        return "reembolso_sin_factura"
    if tx.status == "refunded":
        return "reembolso_ya_aplicado"

    # cast: SQLAlchemy tipa las columnas como Column[...]; los valores son str/datetime.
    tx.status = cast(Any, "refunded")
    tx.refunded_at = cast(Any, _utcnow())
    db.commit()

    _revoke_access_for(db, tx)
    nota = issue_credit_note(db, tx, refund_ref=refund_ref, gross=gross, currency=currency)
    return f"reembolso_aplicado:{nota.get('fiscal_number') or 'sin_comprobante'}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _revoke_access_for(db: Session, tx) -> None:
    """Corta lo que ese cobro había concedido. Una compra puntual pierde su entitlement; una
    suscripción NO se cancela acá (el reembolso de una cuota no es una baja — PayPal manda su
    propio evento de cancelación si además se cancela)."""
    from shared.billing.skus import entitlement_for_sku
    from shared.products.entitlements import revoke_order_entitlement

    if tx.kind != "order":
        return
    try:
        ent = entitlement_for_sku(tx.sku)
    except ValueError:
        ent = None
    if ent is None:
        return
    revoked = revoke_order_entitlement(db, user_id=tx.user_id, sector_key=ent[0],
                                       tier=ent[1].value, note=f"PayPal {tx.provider_ref}")
    logger.info("[billing] reembolso de %s: entitlement revocado=%s", tx.sku, revoked)
