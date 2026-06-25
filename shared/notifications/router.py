"""API del buzón de notificaciones — ``/api/v1/notifications``.

Cada usuario ve y administra SOLO sus propias notificaciones (filtradas por
``user_id == current_user.id``; nunca se exponen ajenas). Cualquier autenticado.
Errores user-facing en español.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.notifications.service import notification_service

router = APIRouter()


@router.get("", summary="Listar mis notificaciones")
async def get_notifications(unread_only: bool = False, limit: int = 50,
                            db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    items = notification_service.list_for_user(
        db, current_user.id, unread_only=unread_only, limit=limit)
    return {"notifications": items, "unread": notification_service.unread_count(db, current_user.id)}


@router.get("/unread-count", summary="Cantidad de notificaciones sin leer")
async def get_unread_count(db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)) -> Dict[str, int]:
    return {"unread": notification_service.unread_count(db, current_user.id)}


@router.post("/{notification_id}/read", summary="Marcar una notificación como leída")
async def post_mark_read(notification_id: str, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    if not notification_service.mark_read(db, current_user.id, notification_id):
        raise HTTPException(status_code=404, detail="Notificación no encontrada.")
    return {"id": notification_id, "read": True}


@router.post("/read-all", summary="Marcar todas mis notificaciones como leídas")
async def post_mark_all_read(db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)) -> Dict[str, int]:
    return {"updated": notification_service.mark_all_read(db, current_user.id)}
