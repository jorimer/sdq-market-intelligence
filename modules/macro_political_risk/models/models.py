"""SQLAlchemy models for the Macro-Political Risk module.

Tables:
  - Country        — Countries in the regional peer set (RD + CA + Caribbean)
  - IRMPSnapshot   — Computed IRMP score for 1 country x 1 period
  - DimensionScore — Per-dimension breakdown for a snapshot (explainability)
"""
import enum

from sqlalchemy import (
    Column,
    Boolean,
    Date,
    Enum,
    Float,
    Integer,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.database.base import Base, UUIDMixin


class RiskBand(str, enum.Enum):
    bajo = "Bajo"
    moderado = "Moderado"
    elevado = "Elevado"
    alto = "Alto"


class Country(UUIDMixin, Base):
    """A country in the IRMP regional peer set."""
    __tablename__ = "mpr_countries"

    iso_code = Column(String(3), unique=True, nullable=False)   # e.g. "DO"
    name = Column(String(120), nullable=False)
    region = Column(String(60), nullable=True)                  # e.g. "Caribe", "Centroamerica"
    is_active = Column(Boolean, default=True, nullable=False)

    snapshots = relationship(
        "IRMPSnapshot", back_populates="country", cascade="all, delete-orphan"
    )


class CountryVariable(UUIDMixin, Base):
    """One sourced IRMP input value: (country, period, variable) → value.

    The store the module lacked: lets a sync (e.g. WGI) persist live source data
    per country/period so the IRMP dataset is assembled from real data instead of
    caller-supplied fixtures.
    """
    __tablename__ = "mpr_country_variables"

    iso_code = Column(String(3), nullable=False)
    period = Column(String(10), nullable=False)   # WGI is annual → "2024"
    variable = Column(String(60), nullable=False)
    value = Column(Float, nullable=True)          # None = missing, never interpolated
    source = Column(String(20), nullable=False, default="WGI")
    # Rich metadata carried alongside the scalar value. For WGI-2025 governance
    # variables: {"se", "ci_lo", "ci_hi", "n_sources", "sources": {CODE: mean}} —
    # the confidence interval, source count and 35-source breakdown behind the
    # 0-100 score. None for legacy scalar sources.
    meta = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("iso_code", "period", "variable", name="uq_mpr_var_country_period"),
        Index("ix_mpr_var_country_period", "iso_code", "period"),
    )


class IRMPSnapshot(UUIDMixin, Base):
    """Computed IRMP for one country and period."""
    __tablename__ = "mpr_irmp_snapshots"
    __table_args__ = (
        UniqueConstraint("country_id", "period_end", name="uq_irmp_country_period"),
        Index("ix_irmp_country_period", "country_id", "period_end"),
    )

    country_id = Column(String, ForeignKey("mpr_countries.id"), nullable=False)
    period_end = Column(Date, nullable=False)
    irmp_score = Column(Float, nullable=False)
    risk_band = Column(Enum(RiskBand), nullable=False)
    peer_set_size = Column(Integer, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
    # Full {dimension: {score, weight, contribution, variables}} breakdown
    breakdown = Column(JSON, nullable=True)

    country = relationship("Country", back_populates="snapshots")
    dimension_scores = relationship(
        "DimensionScore", back_populates="snapshot", cascade="all, delete-orphan"
    )


class DimensionScore(UUIDMixin, Base):
    """One dimension's score within a snapshot (denormalized for querying)."""
    __tablename__ = "mpr_dimension_scores"

    snapshot_id = Column(String, ForeignKey("mpr_irmp_snapshots.id"), nullable=False)
    dimension = Column(String(40), nullable=False)   # macro / external / political / regulatory / events
    score = Column(Float, nullable=False)
    weight = Column(Float, nullable=False)
    contribution = Column(Float, nullable=False)

    snapshot = relationship("IRMPSnapshot", back_populates="dimension_scores")
