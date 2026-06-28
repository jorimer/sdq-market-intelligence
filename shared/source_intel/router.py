"""API del tablero de Inteligencia de Fuentes — ``/api/v1/source-intel`` (admin).

Transversal (vive en ``shared/``). Lecturas y gestión gateadas a admin jerárquico (es
una herramienta interna de cobertura/curaduría). Errores en español.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.auth.dependencies import require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from shared.source_intel.service import (
    SuggestionError,
    board_summary,
    create_suggestion,
    delete_suggestion,
    evaluate,
    get_suggestion,
    list_suggestions,
    scaffold,
    set_status,
)

router = APIRouter()


class _CreateBody(BaseModel):
    kind: str
    title: str
    description: str = ""
    target_axis: Optional[str] = None
    target_gate: Optional[str] = None


class _StatusBody(BaseModel):
    status: str
    decision_note: Optional[str] = None


@router.get("/suggestions", summary="Listar sugerencias del tablero")
async def get_suggestions(
    status: Optional[str] = None, axis: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return {"suggestions": list_suggestions(db, status=status, axis=axis),
            "summary": board_summary(db)}


@router.post("/suggestions", summary="Proponer una sugerencia (fuente/info/sector)")
async def post_suggestion(
    body: _CreateBody, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:
        return create_suggestion(
            db, kind=body.kind, title=body.title, description=body.description,
            proposed_by=current_user.id, target_axis=body.target_axis,
            target_gate=body.target_gate)
    except SuggestionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/suggestions/{suggestion_id}", summary="Detalle de una sugerencia")
async def get_one(
    suggestion_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:
        return get_suggestion(db, suggestion_id)
    except SuggestionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/suggestions/{suggestion_id}/status", summary="Mover de estado (gestión)")
async def patch_status(
    suggestion_id: str, body: _StatusBody, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:
        return set_status(db, suggestion_id, body.status, body.decision_note)
    except SuggestionError as e:
        code = 404 if "no encontrada" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/suggestions/{suggestion_id}/evaluate", summary="Evaluar con IA (o heurística)")
async def post_evaluate(
    suggestion_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Puntúa la sugerencia contra los criterios + la mapea a la brecha. Si no hay IA
    disponible, evaluación heurística honesta (``method``)."""
    try:
        return evaluate(db, suggestion_id)
    except SuggestionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/suggestions/{suggestion_id}/scaffold", summary="Andamiar plan de integración")
async def post_scaffold(
    suggestion_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    """Genera un plan de integración (conector, crosswalk, pasos, riesgos) para la
    sugerencia. Es una propuesta; el build lo ejecuta el dueño/dev (compuerta humana)."""
    try:
        return scaffold(db, suggestion_id)
    except SuggestionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/suggestions/{suggestion_id}", summary="Eliminar una sugerencia")
async def delete_one(
    suggestion_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if not delete_suggestion(db, suggestion_id):
        raise HTTPException(status_code=404, detail="Sugerencia no encontrada.")
    return {"id": suggestion_id, "deleted": True}
