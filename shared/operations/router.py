"""Platform-wide Operation Console endpoints (cross-module).

prefix: /api/v1/operations
Serves every operation any module registered via ``register_operation``.
"""
from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole, role_satisfies
from shared.database.session import get_db
from shared.operations import service as ops

router = APIRouter()


def _require_admin(user: User) -> None:
    # Jerárquico: super_admin ⊇ admin (un chequeo plano `!= admin` dejaba afuera a
    # super_admin, que debe poder todo lo de admin).
    if not role_satisfies(user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")


@router.get("/status", summary="Estado de todas las operaciones")
async def operations_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return ops.all_status(db)


@router.post("/{name}/run", summary="Disparar una operación")
async def run_operation(
    name: str,
    params: Optional[Dict] = Body(None, description="Parámetros (p.ej. {\"period\": \"2025-12\"})"),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    return ops.trigger(name, origin="manual", user_id=current_user.id, params=params or {})


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_hours: Optional[int] = None
    params: Optional[Dict] = None


@router.put("/{name}/schedule", summary="Configurar el agendado de una operación")
async def set_operation_schedule(
    name: str,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    try:
        return ops.set_schedule(db, name, body.enabled, body.interval_hours, body.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
