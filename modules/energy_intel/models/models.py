"""SQLAlchemy models for the Energy Intel module (Eje Energía).

Tables:
  - EnergyScore — computed IRSE (electric-sector resilience) for a period (year).
"""
from sqlalchemy import JSON, Column, Float, Index, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class EnergyScore(UUIDMixin, Base):
    """Computed IRSE (resiliencia del sector eléctrico) for a period (year)."""

    __tablename__ = "en_scores"
    __table_args__ = (
        UniqueConstraint("period", name="uq_en_scores_period"),
        Index("ix_en_scores_period", "period"),
    )

    period = Column(String(10), nullable=False)        # "2025"
    energy_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    coverage = Column(Float, nullable=True)            # frac. del índice con dato real
    capacity_mw = Column(Float, nullable=True)
    capacity_score = Column(Float, nullable=True)
    service_score = Column(Float, nullable=True)
    transition_score = Column(Float, nullable=True)    # penetración renovable (ONE)
    breakdown = Column(JSON, nullable=True)            # dimensions + capacity + service + transition
    model_version = Column(String(10), default="1.0", nullable=False)
