"""SQLAlchemy models for the ESG & Climate module (Eje 7).

Tables:
  - EnvIndicator — one environmental observation (theme/period/value, lineage).
  - ESGScore     — computed exposure + materiality per sector and period.
"""
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Index,
    JSON,
    String,
    UniqueConstraint,
)

from shared.database.base import Base, UUIDMixin


class EnvIndicator(UUIDMixin, Base):
    """One environmental observation with provenance."""
    __tablename__ = "esg_indicators"
    __table_args__ = (
        Index("ix_esg_ind_theme_period", "theme", "period"),
    )

    theme = Column(String(60), nullable=False)
    period = Column(String(10), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    sector_key = Column(String(60), nullable=True)
    unit = Column(String(40), nullable=True)
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class ESGScore(UUIDMixin, Base):
    """Computed ESG/climate exposure + materiality for a sector and period."""
    __tablename__ = "esg_scores"
    __table_args__ = (
        UniqueConstraint("sector_key", "period", name="uq_esg_sector_period"),
        Index("ix_esg_scores_sector_period", "sector_key", "period"),
    )

    sector_key = Column(String(60), nullable=False)
    period = Column(String(10), nullable=False)
    esg_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    material = Column(Boolean, nullable=True)
    materiality_level = Column(String(20), nullable=True)
    breakdown = Column(JSON, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
