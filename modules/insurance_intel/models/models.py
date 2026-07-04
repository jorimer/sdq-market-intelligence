"""SQLAlchemy models for the Insurance Intel module (SIS · SISALRIL).

Mirrors ``pension_intel`` 1:1. Tables:
  - InsuranceEntity   — an insurer (aseguradora) or ARS catalog row.
  - InsuranceSeries   — one observation: a series value for a period, with lineage.
                        ``entity_slug`` NULL = system/market series; set = per-entity.
                        ``dimension`` carries the ramo (line of business) for
                        market series split by line — the ONE/region pattern, so
                        one spine serves both the market pulse and the per-entity face.
  - InsuranceRating   — computed ISF (Índice de Solidez de Aseguradora) per entity/period.
  - InsuranceSnapshot — computed market aggregate for a period (the pulse's output).

Missing values are stored as NULL (never interpolated), per the platform rule.
The ISF entity dimensions (solvency/liquidity from audited statements) are a
declared gap until financials are ingested (F1b) — modeled then on banking_score,
not guessed now.
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


class InsuranceEntity(UUIDMixin, Base):
    """A Dominican insurer (aseguradora) or health-risk manager (ARS)."""
    __tablename__ = "insurance_entities"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_insurance_entity_slug"),
    )

    slug = Column(String(40), nullable=False)        # stable key: "seguros_universal"
    name = Column(String(200), nullable=False)
    entity_type = Column(String(20), default="aseguradora", nullable=False)  # aseguradora | ars
    entity_code = Column(String(20), nullable=True)  # SIS/SISALRIL code, when known
    is_active = Column(Boolean, default=True, nullable=False)


class InsuranceSeries(UUIDMixin, Base):
    """One insurance observation (series x period [x entity] [x ramo]) with provenance."""
    __tablename__ = "insurance_series"
    __table_args__ = (
        UniqueConstraint(
            "series_code", "period", "entity_slug", "dimension",
            name="uq_insurance_series_period_entity_dim",
        ),
        Index("ix_insurance_series_code_period", "series_code", "period"),
        Index("ix_insurance_series_entity", "entity_slug"),
    )

    # Namespaced codes: market → "sis.primas.total_mensual"; per-ramo →
    # "sis.primas.ramo" with dimension=<ramo_slug>; per-entity → "primas_netas"
    # with entity_slug set. Generous cap (Postgres enforces VARCHAR length).
    series_code = Column(String(120), nullable=False)
    period = Column(String(10), nullable=False)        # "2025", "2025-Q4", "2025-12"
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    unit = Column(String(40), nullable=True)           # "RD$", "%", "conteo"
    frequency = Column(String(20), nullable=True)      # "annual" / "quarterly" / "monthly"
    entity_slug = Column(String(40), nullable=True)    # NULL = market; set = per-entity
    dimension = Column(String(40), nullable=True)      # ramo slug (line of business), when split
    # Lineage
    source = Column(String(40), nullable=True)         # "SIS" / "SISALRIL"
    published_at = Column(Date, nullable=True)
    license = Column(String(160), nullable=True)


class InsuranceRating(UUIDMixin, Base):
    """Computed Índice de Solidez de Aseguradora (ISF) for an entity/period.

    A 0-100 band index (Sólida/Adecuada/En vigilancia/Frágil), NOT a credit rating —
    solvency/liquidity are declared gaps until audited statements land (see
    scoring/isf.py). ``coverage`` is the share of the declared methodology backed by
    real data (< 1.0 until estados financieros are ingested).
    """
    __tablename__ = "insurance_ratings"
    __table_args__ = (
        UniqueConstraint("entity_slug", "period", name="uq_insurance_rating_entity_period"),
        Index("ix_insurance_rating_entity_period", "entity_slug", "period"),
    )

    entity_slug = Column(String(40), nullable=False)
    period = Column(String(10), nullable=False)        # as-of label (latest input period)
    overall_score = Column(Float, nullable=True)       # 0-100, NULL = no scoreable data
    band = Column(String(20), nullable=True)           # Sólida / Adecuada / En vigilancia / Frágil
    coverage = Column(Float, nullable=True)            # [0,1] share of methodology with real data
    dimensions = Column(JSON, nullable=True)           # per-dimension breakdown
    model_version = Column(String(10), default="0.1", nullable=False)


class InsuranceSnapshot(UUIDMixin, Base):
    """Computed market aggregate for one period (the pulse's output).

    Stores headline market figures (total premiums, growth, mix by ramo) + counts;
    derived in the sync once the real premium series are wired.
    """
    __tablename__ = "insurance_snapshots"
    __table_args__ = (
        UniqueConstraint("period", name="uq_insurance_snapshot_period"),
    )

    period = Column(String(10), nullable=False)        # snapshot label / as-of period
    # {series_code: value} headline market figures captured at snapshot time
    headline = Column(JSON, nullable=True)
    series_count = Column(Float, nullable=True)
    entity_count = Column(Float, nullable=True)
    model_version = Column(String(10), default="0.1", nullable=False)
