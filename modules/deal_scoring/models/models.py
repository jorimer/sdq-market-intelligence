"""SQLAlchemy models for the Deal Scoring module.

Materializa el registro de deals históricos que entrena el modelo de cierre
(DEAL-Agent-003). 1 fila = 1 deal/oportunidad con sus 10 features + outcome.

Decisiones de esquema (ver DEAL_SCORING_Datos_Entrenamiento_Decision.md):
  - Taxonomía de `Sector` AMPLIADA vs spec (la de 5 no cubre la cartera SDQ:
    minería/energía, fintech, agro, CPG/venture).
  - `deal_type` añadido como feature: "cerrado" no significa lo mismo en un capital
    raise que en un real estate o una compra de cartera → modelar por tipo o usarlo.
  - Las 4 señales de analista son NULLABLE: no existen en data pública; se llenan
    con juicio SDQ (backfill retrospectivo). Modelo reducido válido mientras falten.
  - `closed_successfully` NULLABLE: deals abiertos aún no tienen outcome.
  - `source_folder` + `label_confidence`: trazabilidad y honestidad del label
    (regla de trazabilidad del proyecto, SPECS_OVERVIEW §calidad).

Tabla:
  - HistoricalDeal — registro de deals para entrenamiento/backtest del scorer.
"""
import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
)

from shared.database.base import Base, UUIDMixin


# ─── Enums ────────────────────────────────────────────────────────


class DealType(str, enum.Enum):
    """Naturaleza del deal. 'closed' tiene semántica distinta por tipo."""
    capital_raise = "capital_raise"
    real_estate = "real_estate"
    ma_valuation = "ma_valuation"
    debt_portfolio = "debt_portfolio"
    venture = "venture"
    financing = "financing"
    advisory = "advisory"   # asesoría/mandato — tipo dominante en la cartera SDQ
    other = "other"


class Sector(str, enum.Enum):
    """Taxonomía ampliada vs DEAL-Agent-003 §2.2 (5 sectores no cubren la cartera)."""
    real_estate = "real_estate"
    tourism = "tourism"
    mining_energy = "mining_energy"
    technology = "technology"
    fintech = "fintech"
    agriculture = "agriculture"
    cpg = "cpg"
    other = "other"


class DealStage(str, enum.Enum):
    """Etapa del deal (spec §2.2 Input Schema)."""
    initial = "initial"
    due_diligence = "due_diligence"
    term_sheet = "term_sheet"
    legal = "legal"


class LabelConfidence(str, enum.Enum):
    """Confianza en el outcome etiquetado (curaduría retrospectiva)."""
    alta = "alta"
    media = "media"
    baja = "baja"


# ─── Modelo ───────────────────────────────────────────────────────


class HistoricalDeal(UUIDMixin, Base):
    """Un deal/oportunidad histórico: 10 features del spec + outcome + trazabilidad.

    Las columnas `*_score` mapean a `prepare_features()` en
    `docs/Modelos Propietarios/deal_scoring.py`. `closed_successfully` es el target.
    """

    __tablename__ = "historical_deals"

    # Identidad
    deal_name = Column(String(200), nullable=False)
    # Nombres de tipo explícitos: en Postgres el default 'sector' colisionaría con
    # otros módulos; los fijamos con prefijo deal_.
    deal_type = Column(Enum(DealType, name="deal_type"), nullable=False)

    # Features estructurales (objetivos — extraíbles de modelos financieros / carpeta)
    deal_size_usd = Column(Numeric(18, 2), nullable=True)
    equity_required_pct = Column(Numeric(5, 2), nullable=True)  # 0-100
    sector = Column(Enum(Sector, name="deal_sector"), nullable=False)
    country = Column(String(2), nullable=False)  # ISO-2 (DO, CO, MX, …)
    deal_stage = Column(Enum(DealStage, name="deal_stage"), nullable=True)
    days_since_first_contact = Column(Integer, nullable=True)

    # Señales de analista 0-100 (juicio SDQ — NO existen en data pública)
    promoter_track_record = Column(Integer, nullable=True)
    financial_quality = Column(Integer, nullable=True)
    market_validation = Column(Integer, nullable=True)
    regulatory_readiness = Column(Integer, nullable=True)

    # Target + outcome
    closed_successfully = Column(Boolean, nullable=True)  # 1=cerró, 0=no, NULL=abierto
    outcome_date = Column(Date, nullable=True)

    # Procedencia del label: ¿se etiquetó con el outcome YA conocido (backfill
    # histórico) o se scoreó ANTES de saberlo (cosecha going-forward)? Solo los
    # ex-ante (retrospective=False) son libres de fuga y pueden GRADUAR el modelo.
    # Anti-fabricación: un AUC alto sobre labels retrospectivos es leakage, no skill.
    retrospective = Column(Boolean, nullable=False, default=False,
                           server_default=false())

    # Trazabilidad / calidad del label
    source_folder = Column(Text, nullable=True)
    label_confidence = Column(Enum(LabelConfidence, name="label_confidence"),
                              nullable=False, default=LabelConfidence.baja)
    note = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("deal_name", name="uq_historical_deals_name"),
        Index("ix_historical_deals_type_country", "deal_type", "country"),
        Index("ix_historical_deals_outcome", "closed_successfully"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<HistoricalDeal {self.deal_name!r} type={self.deal_type} "
                f"closed={self.closed_successfully}>")
