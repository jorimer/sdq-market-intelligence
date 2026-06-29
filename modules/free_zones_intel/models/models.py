"""SQLAlchemy models for the Free Zones Intel module (Eje Zonas Francas).

Tables:
  - FreeZoneScore — computed IZF (free-zone attractiveness) for a period (year).
"""
from sqlalchemy import JSON, Column, Float, Index, String, UniqueConstraint

from shared.database.base import Base, UUIDMixin


class FreeZoneScore(UUIDMixin, Base):
    """Computed IZF (atractividad del sector zonas francas) for a period (year)."""

    __tablename__ = "fz_scores"
    __table_args__ = (
        UniqueConstraint("period", name="uq_fz_scores_period"),
        Index("ix_fz_scores_period", "period"),
    )

    period = Column(String(10), nullable=False)        # "2024"
    fz_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    coverage = Column(Float, nullable=True)            # frac. del índice con dato real
    exports_musd = Column(Float, nullable=True)
    investment_musd = Column(Float, nullable=True)
    jobs = Column(Float, nullable=True)
    companies = Column(Float, nullable=True)
    breakdown = Column(JSON, nullable=True)            # dimensions + per-dim metrics + levels
    model_version = Column(String(10), default="1.0", nullable=False)
