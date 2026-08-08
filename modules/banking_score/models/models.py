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
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.database.base import Base, UUIDMixin


# ─── Enums ────────────────────────────────────────────────────────


class BankType(str, enum.Enum):
    """SIB-supervised entity types (Financial Entity Score universe, SPEC §3)."""
    banca_multiple = "banca_multiple"
    aap = "aap"
    banco_ahorro_credito = "banco_ahorro_credito"
    corporacion_credito = "corporacion_credito"
    cambiaria = "cambiaria"
    fiduciaria = "fiduciaria"


class PeriodType(str, enum.Enum):
    quarterly = "quarterly"
    annual = "annual"
    monthly = "monthly"  # SIB historical ledger (Cronología SB) is monthly


class DataSource(str, enum.Enum):
    manual = "manual"
    sib_api = "sib_api"
    csv_upload = "csv_upload"
    sib_pdf = "sib_pdf"  # fiduciary audited-statement PDFs (SIB supervised portal)
    sib_simbad = "sib_simbad"  # SIMBAD public Superset — fallback when the open API lacks a period
    sib_historical = "sib_historical"  # Cronología SB historical CSVs (per-entity monthly, 1947→)


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

    # ── Pre-computed SIB ratios (%, dimensionless) ──
    # Stored directly from the SIB indicadores/solvencia endpoints so the engine
    # can prefer them and avoid mixing units across endpoints (balance is pesos,
    # indicadores are millions). NULL when the SIB didn't report that ratio.
    solvencia_pct = Column(Numeric(10, 4), nullable=True)
    tier1_pct = Column(Numeric(10, 4), nullable=True)
    morosidad_pct = Column(Numeric(10, 4), nullable=True)
    cartera_vigente_pct = Column(Numeric(10, 4), nullable=True)
    cobertura_pct = Column(Numeric(10, 4), nullable=True)
    margen_pct = Column(Numeric(10, 4), nullable=True)
    cost_income_pct = Column(Numeric(10, 4), nullable=True)
    # Cartera-quality ratios computed from a SINGLE SIB endpoint each (so the
    # ratio is unit-safe regardless of that endpoint's unit):
    #   castigos_pct      = castigos / carteraTotal      (indicadores/morosidad-estresada)
    #   exposicion_re_pct = deuda hipotecaria / deuda    (indicadores/riesgo-credito)
    castigos_pct = Column(Numeric(10, 4), nullable=True)
    exposicion_re_pct = Column(Numeric(10, 4), nullable=True)

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

    # Perfil SDQ — dos ejes independientes que reemplazan la lectura del símbolo único.
    # `rating_tier` convive DEPRECADO mientras la superficie migra: retirarlo en el mismo
    # paso que se introduce el reemplazo dejaría sin salida si algo hay que revisar.
    ejecucion_score = Column(Numeric(6, 2), nullable=True)
    resiliencia_score = Column(Numeric(6, 2), nullable=True)
    banda_ejecucion = Column(String(20), nullable=True)
    banda_resiliencia = Column(String(20), nullable=True)

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
    # True cuando el cambio de tier viene de un cambio de METODOLOGÍA (la versión de modelo
    # difiere de la del período anterior), no de un cambio en la entidad. El `action_type`
    # sigue siendo el real —el tier efectivamente bajó o subió— pero sin esta marca una
    # recalibración se lee en el histórico como deterioro de 44 entidades a la vez.
    metodologica = Column(Boolean, default=False, nullable=False)

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

    # NULL = informe de SISTEMA (criteria/wire/datawatch/sector_outlook): describe la
    # metodología o el sistema entero, no cuelga de una entidad.
    bank_id = Column(String, ForeignKey("banks.id"), nullable=True)
    period_end = Column(Date, nullable=True)

    report_type = Column(Enum(ReportType), nullable=False)
    file_path = Column(String(500), nullable=True)  # ruta en disco (legacy/compat)
    file_blob = Column(LargeBinary, nullable=True)  # bytes del PDF — store durable (sobrevive redeploys del FS efímero)
    file_size = Column(Integer, nullable=True)
    narrative_model = Column(String(100), nullable=True)

    status = Column(Enum(ReportStatus), default=ReportStatus.generating)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    generated_by = Column(String, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    bank = relationship("Bank", back_populates="reports")


# ─── ML model artifact ────────────────────────────────────────────


class MlModel(UUIDMixin, Base):
    """Serialized ML model artifact (durable store).

    The trained XGBoost pickle was kept only on ``MODELS_DIR`` (the container's
    ephemeral FS — the app service has no Railway volume), so it vanished on every
    redeploy and ``ml_available`` reverted to false. This table persists the
    pickle bytes in Postgres; the newest row is the active model.
    """
    __tablename__ = "ml_models"

    module = Column(String(50), nullable=False, default="banking_score")
    version = Column(String(50), nullable=True)
    model_blob = Column(LargeBinary, nullable=False)
    metrics = Column(JSON, nullable=True)
    trained_by = Column(String, ForeignKey("users.id"), nullable=True)


# ─── Operation console models ─────────────────────────────────────
# Moved to shared/operations/models.py (platform-wide, cross-module console).
# Tables unchanged: operation_runs, operation_schedules.


# ─── Fideicomisos públicos (public trusts) ────────────────────────
# Trusts are patrimonios autónomos (funds), NOT solvency-rated entities — they get
# their own "Índice de Salud del Fideicomiso" on a separate scale, not SDQ-AAA…D.

class Fideicomiso(UUIDMixin, Base):
    """A public trust (fideicomiso público) managed by a fiduciary."""
    __tablename__ = "fideicomisos"

    name = Column(String, nullable=False)
    slug = Column(String, nullable=True)  # filename-stem key (e.g. "rd-vial")
    fiduciaria_bank_id = Column(String, ForeignKey("banks.id"), nullable=True)
    segment = Column(String, nullable=True)  # operativo|tenedor|desarrollo|social
    source_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("name", name="uq_fideicomiso_name"),)


class FideicomisoData(UUIDMixin, Base):
    """Raw figures extracted from a trust's audited statement (1 row = trust x period)."""
    __tablename__ = "fideicomiso_data"

    fideicomiso_id = Column(String, ForeignKey("fideicomisos.id"), nullable=False)
    period_end = Column(Date, nullable=False)
    period_type = Column(Enum(PeriodType), default=PeriodType.annual)

    activos_totales = Column(Numeric(20, 2), nullable=True)
    pasivos_totales = Column(Numeric(20, 2), nullable=True)
    pasivos_circulantes = Column(Numeric(20, 2), nullable=True)
    patrimonio_fideicomitido = Column(Numeric(20, 2), nullable=True)
    activos_liquidos = Column(Numeric(20, 2), nullable=True)
    resultado_periodo = Column(Numeric(20, 2), nullable=True)
    ingresos_operacionales = Column(Numeric(20, 2), nullable=True)

    source = Column(Enum(DataSource), default=DataSource.sib_pdf)

    __table_args__ = (
        UniqueConstraint("fideicomiso_id", "period_end", name="uq_fideicomiso_period"),
    )


class FideicomisoHealthScore(UUIDMixin, Base):
    """Computed health index for a trust (own scale, not SDQ-AAA…D)."""
    __tablename__ = "fideicomiso_health_scores"

    fideicomiso_id = Column(String, ForeignKey("fideicomisos.id"), nullable=False)
    period_end = Column(Date, nullable=False)

    solvencia_score = Column(Numeric(6, 2), nullable=True)       # null = N/D
    liquidez_score = Column(Numeric(6, 2), nullable=True)
    sostenibilidad_score = Column(Numeric(6, 2), nullable=True)
    overall_score = Column(Numeric(6, 2), nullable=True)
    health_band = Column(String, nullable=True)  # Sólida|Estable|En vigilancia|Frágil|N/D
    segment = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("fideicomiso_id", "period_end", name="uq_fideicomiso_score_period"),
    )


# ─── SIB Historical Ledger (Cronología SB) ────────────────────────


class SibHistoricalLedger(UUIDMixin, Base):
    """Raw historical financial ledger published by the SIB via *Cronología SB*.

    Landing zone (long format: 1 row = entity × period × chart-of-accounts line)
    for the per-entity **monthly** balance sheet (``estado='situacion'``,
    1947→) and income statement (``estado='resultados'``, 1996→). This table is
    the auditable, re-derivable source; it is NOT scored directly — a downstream
    crosswalk pivots it into ``banking_data`` rows (``source=sib_historical``).

    ``row_key`` is a stable hash of the natural key (estado, fecha, entity, the
    four account levels) so re-loading a fresh snapshot upserts the same cell
    instead of duplicating — and so the constraint behaves identically on SQLite
    and Postgres regardless of NULL levels (resultados has no nivel_3/4).
    """
    __tablename__ = "sib_historical_ledger"

    estado = Column(String(12), nullable=False)          # 'situacion' | 'resultados'
    fecha = Column(Date, nullable=False)
    ano = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)
    periodicidad = Column(String(16), nullable=True)     # Mensual | Trimestral | Semestral | Anual

    entidad_code = Column(String(64), nullable=False)    # ENTIDAD (short code)
    entidad_nombre = Column(String(255), nullable=True)
    tipo_entidad = Column(String(96), nullable=True)     # normalised (casing collapsed)
    sector = Column(String(32), nullable=True)           # Público | Privado
    tipo_capital = Column(String(48), nullable=True)

    nivel_1 = Column(String(128), nullable=True)         # Activos | Pasivos | Patrimonio | (P&L lines)
    nivel_2 = Column(String(200), nullable=True)
    nivel_3 = Column(String(200), nullable=True)         # NULL for resultados
    nivel_4 = Column(String(200), nullable=True)         # NULL for resultados

    monto = Column(Numeric(22, 2), nullable=True)
    monto_desagregado = Column(Numeric(22, 2), nullable=True)  # resultados only

    snapshot_date = Column(Date, nullable=True)          # source last-modified
    source_file = Column(String(80), nullable=True)      # e.g. estadosituacion_1947_1996.csv
    row_key = Column(String(40), nullable=False)         # sha1 of natural key

    __table_args__ = (
        UniqueConstraint("row_key", name="uq_sib_hist_row_key"),
        Index("ix_sib_hist_entity_fecha", "entidad_code", "fecha"),
        Index("ix_sib_hist_estado_fecha", "estado", "fecha"),
    )


class SibHistoricalFinancials(UUIDMixin, Base):
    """Derived monthly financials per entity, computed from the raw ledger.

    The crosswalk (``sib_historical_crosswalk``) pivots :class:`SibHistoricalLedger`
    into these wide rows — one per entity per month — with the indicator inputs that
    are *authentically* reconstructable from the accounting ledger. Keyed by
    ``entidad_code`` (not a ``banks`` FK) on purpose: the historical universe includes
    ~180 entities, many long-exited, and matching them to the operational ``banks``
    table would drag in the known matcher pitfalls (APAP→Popular, Bonao→Bonanza). The
    backtest and forensic reports work off the entity code/name directly.

    Balance ratios (morosidad, cobertura, apalancamiento) are point-in-time and safe;
    the P&L magnitudes are stored as the SB reports them (YTD-accumulated within the
    calendar year), so consumers annualise from December or de-accumulate as needed.
    Capital adequacy (Basel) is NOT here — it's regulatory and absent pre-2004; the
    leverage ratio (``apalancamiento_pct`` = patrimonio/activos) is the labelled proxy.
    """
    __tablename__ = "sib_historical_financials"

    entidad_code = Column(String(64), nullable=False)
    entidad_nombre = Column(String(255), nullable=True)
    tipo_entidad = Column(String(96), nullable=True)
    sector = Column(String(32), nullable=True)
    fecha = Column(Date, nullable=False)
    ano = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)

    # ── Balance-derived magnitudes (RD$) ──
    activos_totales = Column(Numeric(22, 2), nullable=True)
    cartera_bruta = Column(Numeric(22, 2), nullable=True)
    cartera_neta = Column(Numeric(22, 2), nullable=True)
    provisiones = Column(Numeric(22, 2), nullable=True)          # positive
    cartera_vencida_90d = Column(Numeric(22, 2), nullable=True)  # +90d + cobranza judicial
    depositos_totales = Column(Numeric(22, 2), nullable=True)
    patrimonio = Column(Numeric(22, 2), nullable=True)
    pasivos_totales = Column(Numeric(22, 2), nullable=True)
    activos_liquidos = Column(Numeric(22, 2), nullable=True)     # efectivo + inversiones + interbancarios

    # ── P&L-derived magnitudes (RD$, YTD-accumulated) ──
    utilidad_neta = Column(Numeric(22, 2), nullable=True)
    ingresos_financieros = Column(Numeric(22, 2), nullable=True)
    gastos_financieros = Column(Numeric(22, 2), nullable=True)
    gastos_operativos = Column(Numeric(22, 2), nullable=True)
    margen_financiero_bruto = Column(Numeric(22, 2), nullable=True)

    # ── Point-in-time ratios (%) ──
    morosidad_pct = Column(Numeric(10, 4), nullable=True)        # vencida / bruta
    cobertura_pct = Column(Numeric(12, 4), nullable=True)        # provisiones / vencida
    apalancamiento_pct = Column(Numeric(10, 4), nullable=True)   # patrimonio / activos (proxy de capital)

    snapshot_date = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("entidad_code", "fecha", name="uq_sib_hist_fin_entity_fecha"),
        Index("ix_sib_hist_fin_fecha", "fecha"),
    )
