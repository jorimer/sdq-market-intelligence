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


class _CheckoutSubBody(BaseModel):
    tier: str = Field(..., description="pro | enterprise")
    return_url: str
    cancel_url: str


class _PayPalConfigBody(BaseModel):
    clientId: Optional[str] = None
    secret: Optional[str] = None
    webhookId: Optional[str] = None
    env: Optional[str] = None
    enabled: Optional[bool] = None
    planPro: Optional[str] = None
    planEnterprise: Optional[str] = None


@router.post("/checkout/order", summary="Iniciar compra puntual de un Deep Dive (self-serve)")
async def post_checkout_order(body: _CheckoutOrderBody, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Crea la orden en el proveedor y devuelve el link de aprobación. 400 si el SKU no
    tiene precio; 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider

    row = price_for(db, body.sku)
    if row is None:
        raise HTTPException(status_code=400, detail="Este producto no tiene precio configurado.")
    provider = get_provider(db)
    try:
        ck = await run_in_threadpool(
            provider.create_order_checkout, sku=body.sku, amount=format(row.amount, "f"),
            currency=row.currency, user_id=current_user.id,
            return_url=body.return_url, cancel_url=body.cancel_url)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"approval_url": ck.approval_url, "provider_ref": ck.provider_ref}


@router.post("/checkout/subscription", summary="Iniciar suscripción a un plan (self-serve)")
async def post_checkout_subscription(body: _CheckoutSubBody, db: Session = Depends(get_db),
                                     current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Crea la suscripción en el proveedor y devuelve el link de aprobación. 503 si la
    pasarela (o el plan del tier) no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider

    if body.tier not in ("pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Plan inválido. Use pro | enterprise.")
    provider = get_provider(db)
    try:
        ck = await run_in_threadpool(
            provider.create_subscription_checkout, tier=body.tier, user_id=current_user.id,
            return_url=body.return_url, cancel_url=body.cancel_url)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"approval_url": ck.approval_url, "provider_ref": ck.provider_ref}


class _CaptureBody(BaseModel):
    order_ref: str = Field(..., description="id de la orden PayPal a capturar")


@router.post("/checkout/order/capture", summary="Capturar una orden aprobada (retorno de PayPal)")
async def post_capture_order(body: _CaptureBody, db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Al volver el usuario de aprobar el pago, captura (cobra) la orden. El acceso lo concede
    el webhook (idempotente). 503 si la pasarela no está configurada."""
    from starlette.concurrency import run_in_threadpool

    from shared.billing.providers import ProviderError, ProviderNotConfigured, get_provider

    provider = get_provider(db)
    try:
        res = await run_in_threadpool(provider.capture_order, body.order_ref)
    except ProviderNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return res


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
        env=body.env, enabled=body.enabled, plan_pro=body.planPro,
        plan_enterprise=body.planEnterprise)


@router.get("/skus", summary="SKUs vendibles del catálogo + su precio vigente (admin)")
async def get_skus(db: Session = Depends(get_db),
                   current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    """Enumera los SKUs canónicos (plan Insight + un Deep Dive por producto del catálogo) con
    su precio vigente si lo tienen, para que el tarifario muestre TODO lo vendible —incluidos
    los SKUs sin precio aún— y el admin pueda fijarlos. Los 'special:{slug}' no se enumeran
    (son a medida)."""
    items = []
    for s in catalog_skus():
        row = price_for(db, s["sku"])
        items.append({
            **s,
            "price": ({"amount": format(row.amount, "f"), "currency": row.currency,
                       "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                       "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                       "label": row.label} if row is not None else None),
        })
    return {"skus": items}


class _TariffBody(BaseModel):
    sku: str = Field(..., description="insight | deep_dive:{sector} | special:{slug}")
    amount: Decimal = Field(..., description="Monto en la moneda (envíe string para exactitud)")
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
            effective_from=body.effective_from, effective_to=body.effective_to,
            label=body.label, note=body.note, created_by=current_user.id)
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
async def get_price(sku: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Precio vigente del SKU a la fecha actual. 404 si no hay tarifa configurada (no se
    debe vender sin precio). Lo consume el catálogo y, en B3, el checkout."""
    row = price_for(db, sku)
    if row is None:
        raise HTTPException(status_code=404, detail="No hay precio vigente para este producto.")
    return {
        "sku": sku,
        "currency": row.currency,
        "amount": format(row.amount, "f"),
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "label": row.label,
    }
