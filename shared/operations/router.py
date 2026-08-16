"""Platform-wide Operation Console endpoints (cross-module).

prefix: /api/v1/operations
Serves every operation any module registered via ``register_operation``.
"""
from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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


@router.get("/llm-spend", summary="Gasto del modelo por disparador, módulo y motivo")
async def llm_spend(
    desde: Optional[date] = Query(
        None, description="Fecha inicial inclusive (AAAA-MM-DD). Por defecto, 30 días atrás"),
    hasta: Optional[date] = Query(
        None, description="Fecha final INCLUSIVE del día completo. Por defecto, hoy"),
    trigger: Optional[str] = Query(
        None, description="Detalle de un disparador; sin él, el resumen agregado"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """El gasto del modelo, consultable en vez de investigable.

    El costo de cada llamada ya se calculaba y se tiraba: los logs del proveedor de
    despliegue solo conservan la versión vigente, así que la única forma de saber en qué se
    iba el dinero era mirar la consola de Anthropic antes y después de cada corrida.

    El rango va por FECHAS y no por una ventana de N días porque la pregunta real es «¿esto
    cuadra con lo que me facturaron?», y la facturación va por ciclo calendario. ``hasta``
    incluye el día completo.

    Se agrupa por DISPARADOR porque esa es la columna que responde: el módulo dice qué
    producto consumió, el disparador dice si lo pidió alguien o si una tarea agendada lo
    generó sola.
    """
    from shared.observability import spend

    _require_admin(current_user)
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400,
                            detail="El rango está invertido: 'desde' es posterior a 'hasta'.")
    if trigger:
        return {"disparador": trigger,
                "llamadas": spend.spend_detail(db, desde=desde, hasta=hasta,
                                               trigger=trigger)}
    return spend.spend_summary(db, desde=desde, hasta=hasta)
