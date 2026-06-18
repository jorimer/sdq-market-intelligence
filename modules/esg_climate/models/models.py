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
    """Computed IRC (climate resilience) for a country/entity and period.

    Re-scoped 2026-06-18 from per-sector to NATIONAL: ``entity_key`` is a country
    ISO3 (the peer set is the Caribbean/LatAm panel). ``material``/
    ``materiality_level`` are legacy sector fields, left nullable and unused."""
    __tablename__ = "esg_scores"
    __table_args__ = (
        UniqueConstraint("entity_key", "period", name="uq_esg_entity_period"),
        Index("ix_esg_scores_entity_period", "entity_key", "period"),
    )

    entity_key = Column(String(60), nullable=False)   # country ISO3 (e.g. "DOM")
    period = Column(String(10), nullable=False)
    esg_score = Column(Float, nullable=True)
    band = Column(String(20), nullable=True)
    material = Column(Boolean, nullable=True)          # legacy (sector materiality), unused
    materiality_level = Column(String(20), nullable=True)  # legacy, unused
    breakdown = Column(JSON, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
