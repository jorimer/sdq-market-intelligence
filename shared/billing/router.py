"""API del tarifario gestionado — ``/api/v1/billing``.

Transversal (vive en ``shared/billing``). Dos planos:
- **Administración del tarifario** (publicar / retirar / listar): admin jerárquico
  (``require_role(admin)``). Es donde el dueño edita precios con vigencia por fechas.
- **Consulta de precio vigente** (``/tariffs/price/{sku}``): cualquier autenticado, para
  alimentar el catálogo y, en B3, el checkout. Errores user-facing en español.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.billing.tariffs import (
    TariffError,
    create_tariff,
    list_tariffs,
    price_for,
    withdraw_tariff,
)
from shared.billing.skus import catalog_skus
from shared.database.session import get_db

router = APIRouter()


# ─── Pago self-serve (Fase 3): checkout + webhook + config del proveedor ───
class _CheckoutOrderBody(BaseModel):
    sku: str = Field(..., description="deep_dive:{sector}")
    return_url: str
    cancel_url: str
    # País de facturación elegido en la confirmación de checkout (ISO-2). Si viene, se guarda
    # en el perfil y define el trato fiscal (RD 18% vs exportación de servicios exenta).
    country: Optional[str] = None
    # RNC/cédula del cliente (opcional): si el cliente de RD lo da, la factura es de crédito
    # fiscal (e-CF tipo 31); si no, consumo (tipo 32).
    tax_id: Optional[str] = None


class _CheckoutSubBody(BaseModel):
    sku: str = Field(..., description="insight:{sector} | all_access | enterprise")
    interval: str = Field("monthly", description="monthly | annual")
    return_url: str
    cancel_url: str
    country: Optional[str] = None
    tax_id: Optional[str] = None


class _QuoteBody(BaseModel):
    sku: str
    interval: str = Field("once", description="once | monthly | annual")
    country: Optional[str] = None


class _CaptureBody(BaseModel):
    order_ref: str = Field(..., description="id de la orden PayPal a capturar")


class _PayPalConfigBody(BaseModel):
    clientId: Optional[str] = None
    secret: Optional[str] = None
    webhookId: Optional[str] = None
    env: Optional[str] = None
    enabled: Optional[bool] = None
    # Mapa de billing plans por (sku, intervalo): {sku: {interval: plan_id}}.
    plans: Optional[Dict[str, Dict[str, str]]] = None


def _resolve_country(db: Session, user: User, chosen: Optional[str],
                     tax_id: Optional[str] = None) -> str:
    """País de facturación efectivo (persiste la elección en el perfil) + guarda el RNC/cédula
    del cliente si vino. Default 'DO' (conservador: tributa)."""
    from shared.billing.tax import normalize_country

    dirty = False
    if tax_id is not None:
        clean = tax_id.strip() or None
        if clean != (user.tax_id or None):
            user.tax_id = clean
            dirty = True
    cc = normalize_country(user.country)
    if chosen:
        cc = normalize_country(chosen)
        if cc != (user.country or ""):
            user.country = cc
            dirty = True
    if dirty:
        db.commit()
    return cc


@router.post("/checkout/order", summary="Iniciar compra puntual de un Deep Dive (self-serve)")
async def post_checkout_order(body: _CheckoutOrderBody, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Crea la orden en el proveedor por el TOTAL (subtotal + impuesto) y devuelve el link de
    aprobación. 400 si el SKU no tiene precio; 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider
    from shared.billing.tax import quote_for

    row = price_for(db, body.sku)
    if row is None:
        raise HTTPException(status_code=400, detail="Este producto no tiene precio configurado.")
    country = _resolve_country(db, current_user, body.country, body.tax_id)
    bd = quote_for(db, subtotal=row.amount, currency=row.currency, country=country)
    provider = get_provider(db)
    try:
        ck = await run_in_threadpool(
            provider.create_order_checkout, sku=body.sku, amount=bd.total,
            currency=bd.currency, user_id=current_user.id,
            return_url=body.return_url, cancel_url=body.cancel_url,
            subtotal=bd.subtotal, tax=bd.tax)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"approval_url": ck.approval_url, "provider_ref": ck.provider_ref,
            "breakdown": bd.as_dict()}


@router.post("/checkout/subscription", summary="Iniciar suscripción a un producto (self-serve)")
async def post_checkout_subscription(body: _CheckoutSubBody, db: Session = Depends(get_db),
                                     current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Crea la suscripción (por-sector o bundle, con periodicidad) y devuelve el link de
    aprobación. 400 si el SKU no es de suscripción o el intervalo no aplica; 503 si la
    pasarela o el plan de ese (sku, intervalo) no está configurado."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider
    from shared.billing.skus import SkuError, allowed_intervals, is_subscription_sku, validate_sku

    try:
        validate_sku(body.sku)
        if not is_subscription_sku(body.sku):
            raise HTTPException(status_code=400, detail="Ese producto no es una suscripción.")
        if body.interval not in allowed_intervals(body.sku):
            raise HTTPException(status_code=400, detail="Periodicidad inválida (use mensual o anual).")
    except SkuError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Impuesto de la suscripción: se aplica sobre el precio base del plan (= subtotal del
    # tarifario). Se pasa el % a PayPal como override por-suscripción. Si no hay precio en el
    # tarifario aún, se cae al % configurado (RD) salvo exención por país.
    from shared.billing.tax import quote_for

    row = price_for(db, body.sku, body.interval)
    country = _resolve_country(db, current_user, body.country, body.tax_id)
    subtotal = row.amount if row is not None else 0
    currency = row.currency if row is not None else "USD"
    bd = quote_for(db, subtotal=subtotal, currency=currency, country=country)
    provider = get_provider(db)
    try:
        ck = await run_in_threadpool(
            provider.create_subscription_checkout, sku=body.sku, interval=body.interval,
            user_id=current_user.id, return_url=body.return_url, cancel_url=body.cancel_url,
            tax_percentage=bd.rate_pct)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"approval_url": ck.approval_url, "provider_ref": ck.provider_ref,
            "breakdown": bd.as_dict() if row is not None else None}


@router.post("/checkout/order/capture", summary="Capturar una orden aprobada (retorno de PayPal)")
async def post_capture_order(body: _CaptureBody, db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Al volver el usuario de aprobar el pago, captura (cobra) la orden **y concede el acceso
    + factura en el momento** (no depende del webhook, que en sandbox puede no existir). El
    webhook, si llega, reconcilia de forma idempotente. 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider
    from shared.billing.settlement import settle_order

    provider = get_provider(db)
    try:
        cap = await run_in_threadpool(provider.capture_order, body.order_ref)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    settled = None
    if (cap.get("status") or "").upper() == "COMPLETED":
        # El pagador viene del custom_id de la captura; se prefiere sobre el usuario de sesión
        # por seguridad (el acceso se concede a quien pagó), con fallback al de sesión.
        settled = settle_order(db, provider.name, order_id=cap.get("order_id") or body.order_ref,
                               user_id=cap.get("user_id") or current_user.id, sku=cap.get("sku"),
                               gross=cap.get("gross"), currency=cap.get("currency"))
    return {**cap, "settled": settled}


class _ActivateSubBody(BaseModel):
    subscription_id: str


@router.post("/checkout/subscription/activate", summary="Activar una suscripción aprobada (retorno)")
async def post_activate_subscription(body: _ActivateSubBody, db: Session = Depends(get_db),
                                     current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Al volver de aprobar la suscripción, consulta su estado en PayPal y, si está ACTIVE,
    **concede el acceso + factura** sin depender del webhook. Idempotente (el webhook, si
    llega, reconcilia). 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider
    from shared.billing.settlement import settle_subscription

    provider = get_provider(db)
    try:
        sub = await run_in_threadpool(provider.get_subscription, body.subscription_id)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    status = (sub.get("status") or "").upper()
    settled = None
    if status in ("ACTIVE", "APPROVED"):
        settled = settle_subscription(
            db, provider.name, subscription_id=body.subscription_id,
            user_id=sub.get("user_id") or current_user.id, sku=sub.get("sku"),
            interval=sub.get("interval"), period_end=sub.get("period_end"),
            gross=sub.get("gross"), currency=sub.get("currency"))
    return {"status": sub.get("status"), "settled": settled}


@router.post("/checkout/quote", summary="Cotizar un SKU con impuestos (desglose)")
async def post_checkout_quote(body: _QuoteBody, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Devuelve el desglose ``Subtotal + Impuesto = Total`` de un (sku, intervalo) para el país
    de facturación dado (o el del perfil). Lo consume la confirmación de checkout para mostrar
    'suscripción + impuestos' antes de ir a PayPal. 404 si el SKU no tiene precio."""
    from shared.billing.tax import normalize_country, quote_for

    row = price_for(db, body.sku, body.interval)
    if row is None:
        raise HTTPException(status_code=404, detail="Este producto aún no tiene precio configurado.")
    country = normalize_country(body.country or current_user.country)
    bd = quote_for(db, subtotal=row.amount, currency=row.currency, country=country)
    return {"sku": body.sku, "interval": body.interval, **bd.as_dict()}


@router.post("/subscription/{subscription_id}/cancel", summary="Cancelar mi suscripción (self-serve)")
async def post_cancel_subscription(subscription_id: str, db: Session = Depends(get_db),
                                   current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Cancela una suscripción del PROPIO usuario: la cancela en PayPal (que emite el webhook
    de baja) y marca el estado local de una vez para reflejarlo sin esperar. 404 si no es del
    usuario; 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider
    from shared.products.models import Subscription
    from shared.products.subscriptions import cancel_subscription

    sub = (db.query(Subscription)
           .filter_by(id=subscription_id, user_id=current_user.id).one_or_none())
    if sub is None:
        raise HTTPException(status_code=404, detail="No encontramos esa suscripción en tu cuenta.")
    if sub.status != "active":
        return {"id": sub.id, "status": sub.status, "already": True}
    if sub.provider == "manual":
        # Suscripción aprovisionada por admin (sin pasarela): baja local directa.
        cancel_subscription(db, sub.id)
        return {"id": sub.id, "status": "cancelled"}

    provider = get_provider(db, sub.provider)
    try:
        await run_in_threadpool(provider.cancel_subscription, sub.provider_subscription_id,
                                reason="Cancelada por el cliente desde la plataforma.")
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    # Reflejar de una vez (el webhook BILLING.SUBSCRIPTION.CANCELLED lo confirma, idempotente).
    cancel_subscription(db, sub.id)
    return {"id": sub.id, "status": "cancelled"}


@router.get("/invoices", summary="Mis facturas (desglose subtotal/impuesto/total)")
async def get_invoices(db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Lista las facturas del propio usuario (cada cobro con su desglose fiscal)."""
    from shared.billing.transactions import list_user_transactions
    return {"invoices": list_user_transactions(db, current_user.id)}


@router.get("/invoices/{transaction_id}/pdf", summary="Descargar mi factura (PDF)")
async def get_invoice_pdf(transaction_id: str, db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Genera y descarga la factura desglosada (PDF con marca SDQ) de una transacción del
    propio usuario. 404 si la factura no es del usuario."""
    from fastapi.responses import Response

    from shared.billing.invoice import render_invoice_pdf
    from shared.billing.transactions import get_user_transaction

    tx = get_user_transaction(db, user_id=current_user.id, transaction_id=transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada.")
    pdf = render_invoice_pdf(db, tx, current_user)
    filename = f"{tx.invoice_number or 'factura'}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                   headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class _TaxConfigBody(BaseModel):
    enabled: Optional[bool] = None
    rate: Optional[str] = Field(None, description="Porcentaje, p.ej. '18'")
    label: Optional[str] = None
    home_country: Optional[str] = Field(None, description="ISO-2 del país que tributa, p.ej. 'DO'")
    exempt_foreign: Optional[bool] = None


@router.get("/tax", summary="Config de impuesto (admin)")
async def get_tax(db: Session = Depends(get_db),
                  current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import get_tax_config
    return get_tax_config(db)


@router.put("/tax", summary="Configurar impuesto (admin)")
async def put_tax(body: _TaxConfigBody, db: Session = Depends(get_db),
                  current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import set_tax_config
    return set_tax_config(db, enabled=body.enabled, rate=body.rate, label=body.label,
                          home_country=body.home_country, exempt_foreign=body.exempt_foreign)


class _IssuerBody(BaseModel):
    name: Optional[str] = None
    rnc: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None


@router.get("/issuer", summary="Datos fiscales del emisor de la factura (admin)")
async def get_issuer(db: Session = Depends(get_db),
                     current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import get_invoice_issuer
    return get_invoice_issuer(db)


@router.put("/issuer", summary="Configurar el emisor de la factura (admin)")
async def put_issuer(body: _IssuerBody, db: Session = Depends(get_db),
                     current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import set_invoice_issuer
    return set_invoice_issuer(db, name=body.name, rnc=body.rnc, address=body.address,
                              email=body.email)


# ─── Secuencias e-NCF (e-CF, DGII) — rangos autorizados por tipo (admin) ───
class _EncfSequenceBody(BaseModel):
    ecf_type: str = Field(..., description="31 | 32 | 46")
    range_from: int
    range_to: int
    current: Optional[int] = None
    expires_at: Optional[datetime] = None
    active: bool = True
    note: Optional[str] = None


@router.get("/encf/sequences", summary="Secuencias e-NCF configuradas (admin)")
async def get_encf_sequences(db: Session = Depends(get_db),
                             current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.billing.encf.sequences import list_sequences
    return {"sequences": list_sequences(db)}


@router.put("/encf/sequences", summary="Cargar/actualizar un rango de e-NCF (admin)")
async def put_encf_sequence(body: _EncfSequenceBody, db: Session = Depends(get_db),
                            current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.billing.encf.sequences import EncfSequenceError, upsert_sequence
    try:
        return upsert_sequence(db, ecf_type=body.ecf_type, range_from=body.range_from,
                               range_to=body.range_to, current=body.current,
                               expires_at=body.expires_at, active=body.active, note=body.note)
    except EncfSequenceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook/paypal", summary="Webhook de PayPal (verificado + idempotente)")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Recibe los eventos de PayPal: verifica la firma, deduplica por event_id y aplica al
    modelo de acceso (entitlement / suscripción). Público (lo llama PayPal), pero solo actúa
    si la firma verifica contra el webhook_id configurado."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.webhook import WebhookError, handle_webhook

    body = await request.body()
    headers = dict(request.headers)
    try:
        return await run_in_threadpool(handle_webhook, db, "paypal", headers, body)
    except WebhookError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/paypal", summary="Config de PayPal (admin, secretos enmascarados)")
async def get_paypal(db: Session = Depends(get_db),
                     current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import paypal_config_masked
    return paypal_config_masked(db)


@router.put("/paypal", summary="Configurar PayPal (admin)")
async def put_paypal(body: _PayPalConfigBody, db: Session = Depends(get_db),
                     current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    from shared.settings.service import set_paypal_config
    return set_paypal_config(
        db, client_id=body.clientId, secret=body.secret, webhook_id=body.webhookId,
        env=body.env, enabled=body.enabled, plans=body.plans)


@router.post("/paypal/sync-plans", summary="Sincronizar billing plans de PayPal con el tarifario (admin)")
async def post_sync_paypal_plans(db: Session = Depends(get_db),
                                 current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Reconcilia tarifario → planes de PayPal: crea (y mapea) un plan por cada SKU de
    suscripción con precio vigente cuyo plan falte o difiera en monto; desactiva el plan
    reemplazado (sus suscriptos siguen cobrando su precio). Idempotente. Las llamadas a
    PayPal son bloqueantes → threadpool."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.plan_sync import sync_paypal_plans
    result = await run_in_threadpool(sync_paypal_plans, db)
    if not result.get("enabled"):
        raise HTTPException(status_code=503, detail="PayPal no está configurado/habilitado.")
    return result


@router.get("/skus", summary="SKUs vendibles del catálogo + su precio vigente (admin)")
async def get_skus(db: Session = Depends(get_db),
                   current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Enumera los SKUs vendibles (Insight y Deep Dive por sector + bundles all_access/
    enterprise) con su precio vigente POR INTERVALO (mensual/anual en suscripciones; once en
    compra puntual), para poblar el tarifario incluyendo los que aún no tienen precio."""
    items = []
    for s in catalog_skus():
        prices = {}
        for interval in s["intervals"]:
            row = price_for(db, s["sku"], interval)
            prices[interval] = ({"amount": format(row.amount, "f"), "currency": row.currency,
                                 "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                                 "label": row.label} if row is not None else None)
        items.append({**s, "prices": prices})
    return {"skus": items}


class _TariffBody(BaseModel):
    sku: str = Field(..., description="insight | deep_dive:{sector} | special:{slug}")
    amount: Decimal = Field(..., description="Monto en la moneda (envíe string para exactitud)")
    interval: str = Field("once", description="once | monthly | annual")
    currency: str = "USD"
    # Fechas en UTC. Un ISO sin offset se interpreta como UTC (no hora local): para
    # programar a una hora local de RD (UTC-4), enviar el offset explícito.
    effective_from: Optional[datetime] = Field(
        None, description="Inicio de vigencia en UTC (None = rige desde ahora)")
    effective_to: Optional[datetime] = Field(
        None, description="Fin de vigencia en UTC (None = abierto)")
    label: Optional[str] = None
    note: Optional[str] = None


@router.get("/tariffs", summary="Listar el tarifario (admin)")
async def get_tariffs(sku: Optional[str] = None, include_inactive: bool = True,
                      db: Session = Depends(get_db),
                      current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Tarifario completo (vigentes / programados / históricos). Filtra por ``sku``."""
    return {"tariffs": list_tariffs(db, sku=sku, include_inactive=include_inactive)}


@router.post("/tariffs", summary="Publicar un precio con vigencia (admin)")
async def post_tariff(body: _TariffBody, db: Session = Depends(get_db),
                      current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Publica una tarifa nueva. No edita el histórico: cada publicación es una fila. Una
    ``effective_from`` futura programa el cambio (B2 alerta a los suscriptos)."""
    try:
        return create_tariff(
            db, sku=body.sku, amount=body.amount, currency=body.currency,
            interval=body.interval, effective_from=body.effective_from,
            effective_to=body.effective_to, label=body.label, note=body.note,
            created_by=current_user.id)
    except TariffError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tariffs/{tariff_id}/withdraw", summary="Retirar una tarifa (admin)")
async def post_withdraw_tariff(tariff_id: str, db: Session = Depends(get_db),
                               current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Retira (``active=False``) una fila de tarifa sin borrar el histórico."""
    if not withdraw_tariff(db, tariff_id):
        raise HTTPException(status_code=404, detail="Tarifa no encontrada.")
    return {"id": tariff_id, "active": False}


@router.get("/tariffs/price/{sku}", summary="Precio vigente de un SKU")
async def get_price(sku: str, interval: str = "once", db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Precio vigente del ``(sku, interval)`` a la fecha actual. 404 si no hay tarifa
    configurada (no se debe vender sin precio). Lo consume el catálogo y el checkout."""
    row = price_for(db, sku, interval)
    if row is None:
        raise HTTPException(status_code=404, detail="No hay precio vigente para este producto.")
    return {
        "sku": sku,
        "interval": interval,
        "currency": row.currency,
        "amount": format(row.amount, "f"),
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "label": row.label,
    }
