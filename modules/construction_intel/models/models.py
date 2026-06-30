"""SQLAlchemy models for the Construction Intel module (Eje Construcción).

Tables:
  - ConstructionScore — computed ICC (construction conjuncture/capacity) for a period (year).
"""
from sqlalchemy import JSON, Column, Float, Index, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class ConstructionScore(UUIDMixin, Base):
    """Computed ICC (Índice de Construcción) for a period (year)."""

    __tablename__ = "const_scores"
    __table_args__ = (
        UniqueConstraint("period", name="uq_const_scores_period"),
        Index("ix_const_scores_period", "period"),
    )

    period = Column(String(10), nullable=False)        # "2025"
    icc_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    coverage = Column(Float, nullable=True)            # frac. del índice con dato real
    permits = Column(Float, nullable=True)             # licencias emitidas en el año
    sqm = Column(Float, nullable=True)                 # m² licenciados en el año
    investment_dop = Column(Float, nullable=True)      # inversión licenciada (RD$) en el año
    prod_growth_3y = Column(Float, nullable=True)      # crec. real PIB construcción, prom. 3y
    breakdown = Column(JSON, nullable=True)            # dimensions + per-dim metrics + levels
    model_version = Column(String(10), default="1.0", nullable=False)
