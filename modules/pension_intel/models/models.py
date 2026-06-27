"""SQLAlchemy models for the Pension Intel module (SIPEN).

Tables:
  - PensionEntity  — an AFP (fund administrator) catalog row.
  - PensionSeries  — one observation: a series value for a period, with lineage.
                     ``entity_slug`` NULL = system/national series; set = per-AFP
                     series (the ONE/region ``dimension`` pattern), so one spine
                     serves both the national pulse and the per-entity face.
  - PensionSnapshot — computed system aggregate for a period (explainability).

Missing values are stored as NULL (never interpolated), per the platform rule.
Per-AFP solvency scoring (RatingResult, wide financial inputs from estados
financieros) lands in F2, once the authoritative statement schema is wired
(channel D) — modeled then on banking_score, not guessed now.
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


class PensionEntity(UUIDMixin, Base):
    """A Dominican AFP (Administradora de Fondos de Pensiones)."""
    __tablename__ = "pension_entities"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_pension_entity_slug"),
    )

    slug = Column(String(40), nullable=False)        # stable key: "afp_siembra"
    name = Column(String(200), nullable=False)
    afp_code = Column(String(20), nullable=True)     # SIPEN code, when known
    is_active = Column(Boolean, default=True, nullable=False)


class PensionSeries(UUIDMixin, Base):
    """One pension observation (series x period [x AFP]) with provenance."""
    __tablename__ = "pension_series"
    __table_args__ = (
        UniqueConstraint(
            "series_code", "period", "entity_slug",
            name="uq_pension_series_period_entity",
        ),
        Index("ix_pension_series_code_period", "series_code", "period"),
        Index("ix_pension_series_entity", "entity_slug"),
    )

    # Namespaced codes: system → "sipen.rentabilidad.cci_nominal_anual";
    # per-AFP → "rentabilidad_nominal_anual" with entity_slug set. Generous cap
    # (Postgres enforces VARCHAR length; SQLite does not — see MacroSeries note).
    series_code = Column(String(120), nullable=False)
    period = Column(String(10), nullable=False)        # "2025", "2025-Q1", "2025-02"
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    unit = Column(String(40), nullable=True)
    frequency = Column(String(20), nullable=True)      # "annual" / "quarterly" / "monthly"
    entity_slug = Column(String(40), nullable=True)    # NULL = system; set = per-AFP
    # Lineage
    source = Column(String(40), nullable=True)         # "SIPEN"
    published_at = Column(Date, nullable=True)
    license = Column(String(160), nullable=True)


class PensionSnapshot(UUIDMixin, Base):
    """Computed system aggregate for one period (the pulse's output).

    F0 stores headline values + counts; the system health index and signals are
    derived in F1 once enough real series are wired.
    """
    __tablename__ = "pension_snapshots"
    __table_args__ = (
        UniqueConstraint("period", name="uq_pension_snapshot_period"),
    )

    period = Column(String(10), nullable=False)        # snapshot label / as-of period
    # {series_code: value} headline national figures captured at snapshot time
    headline = Column(JSON, nullable=True)
    series_count = Column(Float, nullable=True)
    entity_count = Column(Float, nullable=True)
    model_version = Column(String(10), default="0.1", nullable=False)
