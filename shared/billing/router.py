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

from fastapi import APIRouter, Depends, HTTPException
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
