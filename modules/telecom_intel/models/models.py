"""SQLAlchemy models for the Telecom Intel module (Eje Telecomunicaciones).

Tables:
  - TelecomScore — computed IDT (telecom development) for a period (quarter).
"""
from sqlalchemy import JSON, Column, Float, Index, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class TelecomScore(UUIDMixin, Base):
    """Computed IDT (desarrollo telecom) for a period (e.g. '2022-Q1')."""

    __tablename__ = "tel_scores"
    __table_args__ = (
        UniqueConstraint("period", name="uq_tel_scores_period"),
        Index("ix_tel_scores_period", "period"),
    )

    period = Column(String(10), nullable=False)        # "2022-Q1"
    telecom_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    coverage = Column(Float, nullable=True)
    mobile_penetration = Column(Float, nullable=True)
    internet_penetration = Column(Float, nullable=True)
    broadband_share = Column(Float, nullable=True)
    breakdown = Column(JSON, nullable=True)            # dimensions + metrics
    model_version = Column(String(10), default="1.0", nullable=False)
