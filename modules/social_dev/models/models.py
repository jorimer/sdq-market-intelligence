"""SQLAlchemy models for the Social Development module (Eje 5).

Tables:
  - SocialIndicator  — one social observation (with disaggregation + lineage).
  - DevelopmentScore — computed multidimensional development index per entity/period.
"""
from sqlalchemy import (
    Column,
    Date,
    Float,
    Index,
    JSON,
    String,
    UniqueConstraint,
)

from shared.database.base import Base, UUIDMixin


class SocialIndicator(UUIDMixin, Base):
    """One social observation (theme/period/value) with optional disaggregation."""
    __tablename__ = "sd_indicators"
    __table_args__ = (
        Index("ix_sd_ind_theme_period", "theme", "period"),
    )

    theme = Column(String(60), nullable=False)
    period = Column(String(10), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    disaggregation = Column(String(60), nullable=True)  # sexo / region / quintil …
    entity_key = Column(String(60), nullable=True)      # region/group the value belongs to
    unit = Column(String(40), nullable=True)
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class DevelopmentScore(UUIDMixin, Base):
    """Computed development index for one entity (region/group) and period."""
    __tablename__ = "sd_scores"
    __table_args__ = (
        UniqueConstraint("entity_key", "period", name="uq_sd_entity_period"),
        Index("ix_sd_scores_entity_period", "entity_key", "period"),
    )

    entity_key = Column(String(60), nullable=False)
    period = Column(String(10), nullable=False)
    development_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    breakdown = Column(JSON, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
