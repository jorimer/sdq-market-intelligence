"""SQLAlchemy models for the Macro Monitor module (Eje 2).

Tables:
  - MacroSeries   — one observation: a series value for a period, with lineage.
  - MacroSnapshot — computed momentum + signals for a period (explainability).

Missing values are stored as NULL (never interpolated), per the platform rule.
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


class MacroSeries(UUIDMixin, Base):
    """One macro observation (series x period) with provenance."""
    __tablename__ = "mm_series"
    __table_args__ = (
        UniqueConstraint("series_code", "period", name="uq_mm_series_period"),
        Index("ix_mm_series_code_period", "series_code", "period"),
    )

    series_code = Column(String(60), nullable=False)   # e.g. "gdp_growth"
    period = Column(String(10), nullable=False)        # "2025", "2025-Q1", "2025-01"
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    unit = Column(String(40), nullable=True)
    frequency = Column(String(20), nullable=True)      # "annual" / "quarterly" / "monthly"
    # Lineage
    source = Column(String(40), nullable=True)         # "BCRD"
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class MacroSnapshot(UUIDMixin, Base):
    """Computed momentum + signals for one period (the monitor's output)."""
    __tablename__ = "mm_snapshots"
    __table_args__ = (
        UniqueConstraint("period", name="uq_mm_snapshot_period"),
    )

    period = Column(String(10), nullable=False)        # snapshot label / as-of period
    # {series_code: {change, pct_change, acceleration, trend, ...}}
    momentum = Column(JSON, nullable=True)
    # [{signal, framework, severity, ...}]
    signals = Column(JSON, nullable=True)
    series_count = Column(Float, nullable=True)
    signal_count = Column(Float, nullable=True)
    model_version = Column(String(10), default="1.0", nullable=False)
