from uuid import uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    """Mixin that provides a UUID primary key and timestamps."""

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
