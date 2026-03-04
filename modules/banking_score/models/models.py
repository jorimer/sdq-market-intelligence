"""SQLAlchemy models for the Banking Score module.

Extracted from financial-analysis-agent/backend/app/memory/models.py
and adapted to the new modular architecture.

Tables:
  - Bank           — Dominican banking entities regulated by SIB
  - BankingData    — Raw financial inputs (1 row = 1 bank x 1 period)
  - RatingResult   — Computed scores and rating tiers
  - RatingAction   — Tier change communiqués (upgrade/downgrade/etc.)
  - Report         — Generated PDF reports
"""
import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.database.base import Base, UUIDMixin


# ─── Enums ────────────────────────────────────────────────────────


class BankType(str, enum.Enum):
    banca_multiple = "banca_multiple"
    aap = "aap"
    banco_ahorro_credito = "banco_ahorro_credito"


class PeriodType(str, enum.Enum):
    quarterly = "quarterly"
    annual = "annual"


class DataSource(str, enum.Enum):
    manual = "manual"
    sib_api = "sib_api"
    csv_upload = "csv_upload"


class ModelType(str, enum.Enum):
    deterministic = "deterministic"
    ml = "ml"


class ActionType(str, enum.Enum):
    upgrade = "upgrade"
    downgrade = "downgrade"
    confirmacion = "confirmacion"
    observacion = "observacion"


class Outlook(str, enum.Enum):
    positiva = "positiva"
    negativa = "negativa"
    estable = "estable"


class ReportType(str, enum.Enum):
    full_rating = "full_rating"
    scorecard = "scorecard"
    communique = "communique"
    datawatch = "datawatch"
    wire = "wire"
    criteria = "criteria"
    sector_outlook = "sector_outlook"


class ReportStatus(str, enum.Enum):
    generating = "generating"
    completed = "completed"
    error = "error"


# ─── Bank ─────────────────────────────────────────────────────────


class Bank(UUIDMixin, Base):
    """Dominican banking entity regulated by SIB."""
    __tablename__ = "banks"

    name = Column(String(200), unique=True, nullable=False)
    sib_code = Column(String(20), nullable=True)
    bank_type = Column(Enum(BankType), nullable=False)
    total_assets = Column(Numeric(18, 2), nullable=True)
    peer_group = Column(String(50), nullable=True)  # large, medium, small
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    banking_data = relationship("BankingData", back_populates="bank", cascade="all, delete-orphan")
    rating_results = relationship("RatingResult", back_populates="bank", cascade="all, delete-orphan")
    rating_actions = relationship("RatingAction", back_populates="bank", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="bank", cascade="all, delete-orphan")


# ─── BankingData ──────────────────────────────────────────────────


class BankingData(UUIDMixin, Base):
    """Raw financial data — one row per bank per period."""
    __tablename__ = "banking_data"

    bank_id = Column(String, ForeignKey("banks.id"), nullable=False)
    period_end = Column(Date, nullable=False)
    period_type = Column(Enum(PeriodType), default=PeriodType.quarterly)

    # ── Solidez Financiera inputs ──
    patrimonio_tecnico = Column(Numeric(18, 2), nullable=True)
    apr = Column(Numeric(18, 2), nullable=True)
    capital_primario = Column(Numeric(18, 2), nullable=True)
    exposicion_total = Column(Numeric(18, 2), nullable=True)
    capital_tier1 = Column(Numeric(18, 2), nullable=True)
    contingentes = Column(Numeric(18, 2), nullable=True)
    riesgo_mercado = Column(Numeric(18, 2), nullable=True)
    provisiones = Column(Numeric(18, 2), nullable=True)
    cartera_vencida_90d = Column(Numeric(18, 2), nullable=True)
    activos_totales = Column(Numeric(18, 2), nullable=True)

    # ── Calidad de Activos inputs ──
    cartera_bruta = Column(Numeric(18, 2), nullable=True)
    cartera_categoria_a = Column(Numeric(18, 2), nullable=True)
    cartera_total = Column(Numeric(18, 2), nullable=True)
    suma_top10 = Column(Numeric(18, 2), nullable=True)
    hhi_sectorial_raw = Column(Numeric(12, 4), nullable=True)
    castigos = Column(Numeric(18, 2), nullable=True)
    exposicion_re = Column(Numeric(18, 2), nullable=True)
    cartera_a_prev = Column(Numeric(18, 2), nullable=True)

    # ── Eficiencia y Rentabilidad inputs ──
    utilidad_neta = Column(Numeric(18, 2), nullable=True)
    activos_promedio = Column(Numeric(18, 2), nullable=True)
    patrimonio_promedio = Column(Numeric(18, 2), nullable=True)
    ingresos_financieros = Column(Numeric(18, 2), nullable=True)
    gastos_financieros = Column(Numeric(18, 2), nullable=True)
    activos_productivos_avg = Column(Numeric(18, 2), nullable=True)
    gastos_operacionales = Column(Numeric(18, 2), nullable=True)
    ingresos_operacionales = Column(Numeric(18, 2), nullable=True)

    # ── Liquidez inputs ──
    caja_valores = Column(Numeric(18, 2), nullable=True)
    pasivos_cp = Column(Numeric(18, 2), nullable=True)
    cartera_neta = Column(Numeric(18, 2), nullable=True)
    depositos_totales = Column(Numeric(18, 2), nullable=True)
    activos_liquidos = Column(Numeric(18, 2), nullable=True)
    pasivos_exigibles = Column(Numeric(18, 2), nullable=True)

    # ── Diversificación inputs ──
    hhi_ingresos_raw = Column(Numeric(12, 4), nullable=True)

    # ── Metadata ──
    source = Column(Enum(DataSource), default=DataSource.manual)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=True)

    # Relationships
    bank = relationship("Bank", back_populates="banking_data")

    __table_args__ = (
        UniqueConstraint("bank_id", "period_end", name="uq_banking_data_bank_period"),
        Index("ix_banking_data_bank_period", "bank_id", "period_end"),
    )


# ─── RatingResult ─────────────────────────────────────────────────


class RatingResult(UUIDMixin, Base):
    """Computed scores and rating tier for a bank/period."""
    __tablename__ = "rating_results"

    bank_id = Column(String, ForeignKey("banks.id"), nullable=False)
    period_end = Column(Date, nullable=False)

    # Overall
    overall_score = Column(Numeric(6, 2), nullable=False)
    rating_tier = Column(String(10), nullable=False)

    # Sub-component scores
    solidez_score = Column(Numeric(6, 2), nullable=True)
    calidad_score = Column(Numeric(6, 2), nullable=True)
    eficiencia_score = Column(Numeric(6, 2), nullable=True)
    liquidez_score = Column(Numeric(6, 2), nullable=True)
    diversificacion_score = Column(Numeric(6, 2), nullable=True)

    # Full indicator breakdown
    indicator_details = Column(JSON, nullable=True)

    # Model info
    model_type = Column(Enum(ModelType), default=ModelType.deterministic)
    model_version = Column(String(20), default="1.0")

    # Metadata
    created_by = Column(String, ForeignKey("users.id"), nullable=True)

    # Relationships
    bank = relationship("Bank", back_populates="rating_results")

    __table_args__ = (
        UniqueConstraint("bank_id", "period_end", "model_type", name="uq_rating_bank_period_model"),
        Index("ix_rating_results_bank_period", "bank_id", "period_end"),
    )


# ─── RatingAction ─────────────────────────────────────────────────


class RatingAction(UUIDMixin, Base):
    """Rating action communiqué — records tier changes."""
    __tablename__ = "rating_actions"

    bank_id = Column(String, ForeignKey("banks.id"), nullable=False)
    period_end = Column(Date, nullable=False)

    # Action classification
    action_type = Column(Enum(ActionType), nullable=False)

    # Previous rating
    previous_period_end = Column(Date, nullable=True)
    previous_score = Column(Numeric(6, 2), nullable=True)
    previous_tier = Column(String(10), nullable=True)

    # New (current) rating
    new_score = Column(Numeric(6, 2), nullable=False)
    new_tier = Column(String(10), nullable=False)

    # Computed deltas
    score_delta = Column(Numeric(6, 2), nullable=True)
    tier_levels_changed = Column(Integer, default=0)

    # Outlook
    outlook = Column(Enum(Outlook), default=Outlook.estable)

    # Sub-component comparison
    previous_sub_components = Column(JSON, nullable=True)
    new_sub_components = Column(JSON, nullable=True)

    # Communiqué report link
    communique_report_id = Column(String, ForeignKey("reports.id"), nullable=True)

    # Metadata
    created_by = Column(String, ForeignKey("users.id"), nullable=True)

    # Relationships
    bank = relationship("Bank", back_populates="rating_actions")
    communique_report = relationship("Report", foreign_keys=[communique_report_id])


# ─── Report ───────────────────────────────────────────────────────


class Report(UUIDMixin, Base):
    """Generated PDF report."""
    __tablename__ = "reports"

    bank_id = Column(String, ForeignKey("banks.id"), nullable=False)
    period_end = Column(Date, nullable=True)

    report_type = Column(Enum(ReportType), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)
    narrative_model = Column(String(100), nullable=True)

    status = Column(Enum(ReportStatus), default=ReportStatus.generating)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    generated_by = Column(String, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    bank = relationship("Bank", back_populates="reports")
