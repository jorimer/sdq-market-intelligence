"""API del monitor de productos — ``/api/v1/products``.

Transversal (vive en ``shared/``). Lecturas: cualquier usuario autenticado. Activación
y recálculo: admin (jerárquico → super_admin pasa). Errores en español.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.products.activation import ActivationError, activate, deactivate
from shared.products.registry import CATALOG_BY_KEY
from shared.products.service import build_matrix, recompute_readiness, sector_detail
from shared.products.tiers import ProductTier

router = APIRouter()


def _parse_tier(tier: str) -> ProductTier:
    try:
        return ProductTier(tier)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Nivel inválido '{tier}'. Use pulse | insight | deep_dive.")


def _require_sector(sector: str) -> str:
    if sector not in CATALOG_BY_KEY:
        raise HTTPException(status_code=404, detail=f"Sector '{sector}' no está en el catálogo.")
    return sector


@router.get("/readiness", summary="Matriz de readiness sector × nivel + activación")
async def get_readiness(db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return build_matrix(db)


@router.get("/readiness/{sector}", summary="Detalle de readiness de un sector")
async def get_sector_readiness(sector: str, db: Session = Depends(get_db),
                               current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return sector_detail(db, _require_sector(sector))


@router.post("/readiness/recompute", summary="Recalcular readiness (admin)")
async def post_recompute(db: Session = Depends(get_db),
                         current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    res = recompute_readiness(db)
    return {**res, "matrix": build_matrix(db)}


@router.post("/{sector}/{tier}/activate", summary="Exponer al público (admin, gated)")
async def post_activate(sector: str, tier: str, db: Session = Depends(get_db),
                        current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    sector = _require_sector(sector)
    pt = _parse_tier(tier)
    try:
        row = activate(db, sector, pt, user_id=current_user.id)
    except ActivationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"sector_key": sector, "tier": pt.value, "is_active": row.is_active,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None}


@router.post("/{sector}/{tier}/deactivate", summary="Retirar del acceso público (admin)")
async def post_deactivate(sector: str, tier: str, db: Session = Depends(get_db),
                          current_user: User = Depends(require_role(UserRole.admin))) -> Dict[str, Any]:
    sector = _require_sector(sector)
    pt = _parse_tier(tier)
    row = deactivate(db, sector, pt)
    return {"sector_key": sector, "tier": pt.value, "is_active": row.is_active}
