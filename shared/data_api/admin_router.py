"""Administración de llaves de la Data API — ``/api/v1/admin/data-api``.

Vive en el namespace INTERNO (``/api/v1``) y se autentica con la sesión de la SPA: es la
consola del dueño, no parte del contrato público. Solo admin.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import require_role
from shared.auth.models import User, UserRole
from shared.data_api import service
from shared.data_api.manifest import build_manifest
from shared.database.session import get_db

router = APIRouter()


class CreateKeyRequest(BaseModel):
    user_id: str = Field(..., description="Usuario dueño: la llave hereda sus entitlements.")
    name: str = Field(..., max_length=80)
    client_ref: Optional[str] = Field(None, max_length=60)
    usage: str = Field(
        "external",
        description=("'internal' = insumo de análisis propio, el dato no sale hacia "
                     "terceros (habilita fuentes no-comerciales); 'external' = podría "
                     "reexponerlo."),
    )
    rate_limit_per_minute: int = 60
    quota_per_month: Optional[int] = None
    expires_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=255)


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateKeyRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Emite una llave. El token va en la respuesta y no se puede recuperar después."""
    owner = db.query(User).filter(User.id == body.user_id).one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="El usuario dueño no existe.")
    try:
        return service.create_key(
            db, user_id=body.user_id, name=body.name, client_ref=body.client_ref,
            usage=body.usage,
            rate_limit_per_minute=body.rate_limit_per_minute,
            quota_per_month=body.quota_per_month, expires_at=body.expires_at,
            note=body.note,
        )
    except service.ApiKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/keys")
async def list_keys(
    user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> List[Dict[str, Any]]:
    return service.list_keys(db, user_id=user_id)


@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:
        return service.revoke_key(db, key_id=key_id, revoked_by=str(admin.id))
    except service.ApiKeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/keys/{key_id}/usage")
async def key_usage(
    key_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return service.usage_summary(db, key_id=key_id, limit=min(max(limit, 1), 500))


@router.get("/manifest")
async def manifest(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Vista interna COMPLETA del manifiesto, incluida la cuarentena.

    Es el tablero que responde "¿por qué esta serie no le llega al cliente?" sin tener
    que leer código: cada activo retenido trae su razón."""
    m = build_manifest(db)
    return {
        "generated_at": m.generated_at,
        "summary": m.summary,
        "assets": [a.to_dict() for a in m.assets],
    }
