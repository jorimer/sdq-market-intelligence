"""Servicio de notificaciones in-app (persistido).

El modelo ``Notification`` (tabla ``notifications``, creada en la migración inicial) es el
buzón por-usuario. Hasta B2 el servicio era un stub que solo logueaba; ahora persiste para
que las alertas (p.ej. un cambio de tarifa) sean visibles por el suscripto. La delivery y
la lectura son genéricas (viven acá); el CONTENIDO específico (billing) lo arma quien
notifica. Texto en español (doctrina: strings backend-generados quedan en español).
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, String, Text
from sqlalchemy.orm import Session

from shared.database.base import Base, UUIDMixin

logger = logging.getLogger(__name__)


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"

    user_id = Column(String, nullable=False, index=True)
    type = Column(String(50), nullable=False)  # info, warning, error, success
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    read = Column(Boolean, default=False, nullable=False)


def _serialize(n: Notification) -> Dict[str, Any]:
    return {
        "id": n.id, "type": n.type, "title": n.title, "body": n.body,
        "read": bool(n.read),
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


class NotificationService:
    """Buzón in-app por usuario: crear (persistido), listar, marcar leído."""

    def create(self, db: Session, *, user_id: str, type: str, title: str,
               body: str = "") -> Notification:
        """Persiste una notificación para un usuario. Devuelve la fila creada."""
        row = Notification(user_id=user_id, type=type, title=title, body=body, read=False)
        db.add(row)
        db.commit()
        logger.info("NOTIFICATION [%s] to user %s: %s", type, user_id, title)
        return row

    def list_for_user(self, db: Session, user_id: str, *, unread_only: bool = False,
                      limit: int = 50) -> List[Dict[str, Any]]:
        """Notificaciones del usuario, más recientes primero. ``unread_only`` filtra leídas."""
        q = db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            q = q.filter(Notification.read.is_(False))
        rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
        return [_serialize(r) for r in rows]

    def unread_count(self, db: Session, user_id: str) -> int:
        return (db.query(Notification)
                .filter(Notification.user_id == user_id, Notification.read.is_(False))
                .count())

    def mark_read(self, db: Session, user_id: str, notification_id: str) -> bool:
        """Marca una notificación PROPIA como leída. Devuelve False si no existe o no es
        del usuario (no se revela la existencia de notificaciones ajenas)."""
        row = (db.query(Notification)
               .filter(Notification.id == notification_id,
                       Notification.user_id == user_id).one_or_none())
        if row is None:
            return False
        row.read = True
        db.commit()
        return True

    def mark_all_read(self, db: Session, user_id: str) -> int:
        """Marca todas las del usuario como leídas. Devuelve cuántas cambiaron."""
        n = (db.query(Notification)
             .filter(Notification.user_id == user_id, Notification.read.is_(False))
             .update({Notification.read: True}, synchronize_session=False))
        db.commit()
        return n

    def send(self, user_id: str, type: str, title: str, body: str = "") -> None:
        """Compat: notificación sin persistir (solo log). Preferir ``create`` con sesión."""
        logger.info("NOTIFICATION [%s] to user %s: %s — %s", type, user_id, title, body)


notification_service = NotificationService()
