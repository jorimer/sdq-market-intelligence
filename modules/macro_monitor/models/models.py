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

    # Short API codes ("gdp_growth") AND the Excel engine's hierarchical codes
    # ("bcrd.xls.<file>.<metric>", e.g.
    # "bcrd.xls.ipc_base_2019_2020_serie_referencial.variacion_porcentual_con_dic"
    # = 73 chars). PostgreSQL ENFORCES VARCHAR length (SQLite does not), so a too-
    # short cap silently passes dev/tests and then 502s in prod with
    # StringDataRightTruncation. Keep this generous for engine-generated codes.
    series_code = Column(String(255), nullable=False)
    period = Column(String(10), nullable=False)        # "2025", "2025-Q1", "2025-01"
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    unit = Column(String(40), nullable=True)
    frequency = Column(String(20), nullable=True)      # "annual" / "quarterly" / "monthly"
    # Lineage
    source = Column(String(40), nullable=True)         # "BCRD"
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class ExcelFileReport(UUIDMixin, Base):
    """Per-file outcome of running the AI-native engine over the BCRD Excel corpus.

    One row per source file (latest run), so the coverage report is queryable:
    how many files resolved, by which method, what's flagged for review, what
    failed. Populated by the batch runner; upserted by ``file_url``.
    """
    __tablename__ = "mm_excel_reports"
    __table_args__ = (
        UniqueConstraint("file_url", name="uq_mm_excel_file"),
        Index("ix_mm_excel_status", "status"),
    )

    file_url = Column(String(500), nullable=False)
    filename = Column(String(200), nullable=True)
    sector = Column(String(60), nullable=True)
    status = Column(String(20), nullable=False)        # "ok" | "flagged" | "failed"
    method = Column(String(20), nullable=True)         # heuristic | claude | cached
    orientation = Column(String(20), nullable=True)
    frequency = Column(String(20), nullable=True)
    confidence = Column(Float, nullable=True)
    n_records = Column(Float, nullable=True)
    n_series = Column(Float, nullable=True)
    n_flagged = Column(Float, nullable=True)
    persisted = Column(Float, nullable=True)           # observations upserted to MacroSeries
    error = Column(String(500), nullable=True)
    flags = Column(JSON, nullable=True)                # [{code, flags:[...]}] for flagged series


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
