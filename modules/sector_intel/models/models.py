"""SQLAlchemy models for the Sector Intel module (Eje 3).

Tables:
  - Sector         — a sector in scope (anchor sectors first).
  - SectorVariable — raw IAI input per sector/dimension/variable (lineage).
  - SectorScore    — computed IAI + SGPS for a sector and period.
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


class Sector(UUIDMixin, Base):
    """A sector in scope for IAI/SGPS."""
    __tablename__ = "si_sectors"

    code = Column(String(40), unique=True, nullable=False)   # "turismo"
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class SectorVariable(UUIDMixin, Base):
    """One raw IAI input value (sector x dimension x variable) with provenance."""
    __tablename__ = "si_variables"
    __table_args__ = (
        Index("ix_si_var_sector_period", "sector_code", "period"),
    )

    sector_code = Column(String(40), nullable=False)
    dimension = Column(String(40), nullable=False)
    variable = Column(String(60), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    period = Column(String(10), nullable=True)
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class SectorScore(UUIDMixin, Base):
    """Computed IAI + SGPS for a sector and period."""
    __tablename__ = "si_scores"
    __table_args__ = (
        UniqueConstraint("sector_code", "period", name="uq_si_sector_period"),
        Index("ix_si_scores_sector_period", "sector_code", "period"),
    )

    sector_code = Column(String(40), nullable=False)
    period = Column(String(10), nullable=False)
    iai_score = Column(Float, nullable=True)
    iai_band = Column(String(20), nullable=True)
    sgps_score = Column(Float, nullable=True)
    iai_breakdown = Column(JSON, nullable=True)
    sgps_breakdown = Column(JSON, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
