import logging

from sqlalchemy import Boolean, Column, String, Text

from shared.database.base import Base, UUIDMixin

logger = logging.getLogger(__name__)


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"

    user_id = Column(String, nullable=False, index=True)
    type = Column(String(50), nullable=False)  # info, warning, error, success
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    read = Column(Boolean, default=False, nullable=False)


class NotificationService:
    """Stub notification service — logs to console for MVP."""

    def send(self, user_id: str, type: str, title: str, body: str = "") -> None:
        """Send a notification (currently just logs it)."""
        logger.info(
            "NOTIFICATION [%s] to user %s: %s — %s",
            type, user_id, title, body,
        )


notification_service = NotificationService()
