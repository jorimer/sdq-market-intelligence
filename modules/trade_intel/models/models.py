"""SQLAlchemy models for the Trade Intel module (Eje 6).

Tables:
  - TradeFlow  — one trade observation (product x direction x period) with lineage.
  - TradeScore — computed concentration / dependency / resilience for a period.
"""
import enum

from sqlalchemy import (
    Column,
    Date,
    Enum,
    Float,
    Index,
    JSON,
    String,
)

from shared.database.base import Base, UUIDMixin


class TradeDirection(str, enum.Enum):
    export = "export"
    import_ = "import"


class TradeFlow(UUIDMixin, Base):
    """One trade flow: a product value for a period and direction, with provenance."""
    __tablename__ = "ti_flows"
    __table_args__ = (
        Index("ix_ti_flows_period_dir", "period", "direction"),
    )

    product = Column(String(120), nullable=False)
    direction = Column(Enum(TradeDirection), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    period = Column(String(10), nullable=False)        # "2025", "2025-Q1"
    partner = Column(String(80), nullable=True)
    unit = Column(String(40), nullable=True)
    # Lineage
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class TradeScore(UUIDMixin, Base):
    """Computed trade-resilience score for one period."""
    __tablename__ = "ti_scores"
    __table_args__ = (
        Index("ix_ti_scores_period", "period", unique=True),
    )

    period = Column(String(10), nullable=False)
    hhi_exports = Column(Float, nullable=True)
    export_diversification = Column(Float, nullable=True)
    import_dependency = Column(Float, nullable=True)
    resilience_score = Column(Float, nullable=True)
    breakdown = Column(JSON, nullable=True)            # full compute output
    model_version = Column(String(10), default="1.0", nullable=False)
