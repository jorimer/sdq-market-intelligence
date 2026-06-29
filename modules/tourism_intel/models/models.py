"""SQLAlchemy models for the Tourism Intel module (Eje Turismo).

Tables:
  - TourismScore — computed ITT (tourism-demand traction) for a period (year).
"""
from sqlalchemy import JSON, Column, Float, Index, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class TourismScore(UUIDMixin, Base):
    """Computed ITT (tracción turística del destino RD) for a period (year)."""

    __tablename__ = "tour_scores"
    __table_args__ = (
        UniqueConstraint("period", name="uq_tour_scores_period"),
        Index("ix_tour_scores_period", "period"),
    )

    period = Column(String(10), nullable=False)        # "2025"
    itt_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    coverage = Column(Float, nullable=True)            # frac. del índice con dato real
    nonresident = Column(Float, nullable=True)         # llegadas de no residentes (último año)
    foreign = Column(Float, nullable=True)             # extranjeros no residentes (último año)
    breakdown = Column(JSON, nullable=True)            # dimensions + per-dim metrics + levels
    model_version = Column(String(10), default="1.0", nullable=False)
