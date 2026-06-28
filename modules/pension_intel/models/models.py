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


class PensionRating(UUIDMixin, Base):
    """Computed Índice de Solidez de AFP (ISA) for an AFP/period.

    A 0-100 band index (Sólida/Adecuada/En vigilancia/Frágil), NOT a credit rating —
    solvency is a declared gap (see scoring/isa.py). ``coverage`` is the share of the
    declared methodology backed by real data (< 1.0 until estados financieros land).
    """
    __tablename__ = "pension_ratings"
    __table_args__ = (
        UniqueConstraint("entity_slug", "period", name="uq_pension_rating_entity_period"),
        Index("ix_pension_rating_entity_period", "entity_slug", "period"),
    )

    entity_slug = Column(String(40), nullable=False)
    period = Column(String(10), nullable=False)        # as-of label (latest input period)
    overall_score = Column(Float, nullable=True)       # 0-100, NULL = no scoreable data
    band = Column(String(20), nullable=True)           # Sólida / Adecuada / En vigilancia / Frágil
    coverage = Column(Float, nullable=True)            # [0,1] share of methodology with real data
    dimensions = Column(JSON, nullable=True)           # per-dimension breakdown (raw/score/weight/provenance)
    model_version = Column(String(10), default="0.1", nullable=False)


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


class PensionHolding(UUIDMixin, Base):
    """One line of the pension funds' investment portfolio (cartera de inversiones).

    Source: the SIPEN quarterly bulletin, *Cuadro 6.1 — Composición de la cartera de
    inversiones de los fondos de pensiones por emisor (RD$)*. Each row is an issuer
    (``issuer``) grouped under a regulatory sub-sector (``sub_sector``); group-header
    rows carry ``is_subtotal=True`` and their amount equals the sum of their children
    (detected structurally, so the leaves reconcile to the table TOTAL).

    This is the cross-module gem: ``Ministerio de Hacienda`` / ``Banco Central`` =
    public-debt holdings (Macro/BCRD), bank issuers = pension-fund exposure per bank
    (Banca). Cross keys are resolved at ingest from public data — never by reading
    another module's tables (modules talk via events). Missing amounts stay NULL.
    """
    __tablename__ = "pension_holdings"
    __table_args__ = (
        UniqueConstraint("period", "fund", "issuer_slug",
                         name="uq_pension_holding_period_fund_issuer"),
        Index("ix_pension_holding_period_fund", "period", "fund"),
        Index("ix_pension_holding_issuer", "issuer_slug"),
    )

    period = Column(String(10), nullable=False)        # "2026-Q1" (quarterly, from the bulletin)
    fund = Column(String(40), nullable=False)          # "cci" (PR1) | per-complementary fund (later)
    sub_sector = Column(String(120), nullable=True)    # "Ministerio de Hacienda" | "Bancos Múltiples" | …
    issuer = Column(String(200), nullable=False)       # issuer label, verbatim from the bulletin
    issuer_slug = Column(String(80), nullable=False)   # stable normalized key
    amount = Column(Float, nullable=True)              # RD$ (NULL = absent, never interpolated)
    pct = Column(Float, nullable=True)                 # share of the fund (%)
    is_subtotal = Column(Boolean, default=False, nullable=False)  # sub-sector group header (sum of children)
    # Cross-module keys (resolved at ingest from public data, see cartera crosswalk)
    bank_entity_slug = Column(String(40), nullable=True)   # banking_score match, when the issuer is a bank
    macro_class = Column(String(20), nullable=True)        # "deuda_publica" (Hacienda) | "bcrd" | None
    # Lineage
    source = Column(String(40), nullable=True)         # "SIPEN"
    published_at = Column(Date, nullable=True)
    license = Column(String(160), nullable=True)
