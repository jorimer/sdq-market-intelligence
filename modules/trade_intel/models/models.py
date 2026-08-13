"""SQLAlchemy models for the Trade Intel module (Eje 6).

Tables:
  - TradeFlow  — one trade observation (product x direction x period) with lineage.
  - TradeScore — computed concentration / dependency / resilience for a period.
"""
import enum

from typing import Any

from sqlalchemy import (
    Column,
    Date,
    Enum,
    Float,
    Index,
    JSON,
    String,
    Text,
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

    product = Column(Text, nullable=False)  # full HS chapter description (can exceed 120)
    direction = Column(Enum(TradeDirection), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    period = Column(String(10), nullable=False)        # "2025", "2025-Q1"
    partner = Column(String(80), nullable=True)
    unit = Column(String(40), nullable=True)
    # Lineage
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)


class TradePartnerChapter(UUIDMixin, Base):
    """Comercio bilateral ABIERTO POR CAPÍTULO: qué bienes vienen de QUÉ socio.

    **Tabla propia y no una tercera clase de fila en ``ti_flows``.** Esa tabla ya mezcla dos
    tipos distinguidos por un centinela en ``product`` (capítulos del mundo y comercio por
    país) y tiene una ruta que borra por período. Una fila socio × capítulo sería
    indistinguible por ``product`` de una fila del mundo, así que cualquier consumidor que
    sume por producto contaría dos veces — el mismo defecto de agregación que este repo ya
    pagó caro. Separada, ninguna consulta existente cambia de comportamiento.

    Fuente: UN Comtrade (anual). La DGA no puede suplirlo: publica capítulo × valor SIN país
    de origen.
    """
    __tablename__ = "ti_partner_chapters"
    __table_args__ = (
        Index("ix_ti_pc_period_partner", "period", "partner", "direction"),
        Index("ix_ti_pc_unico", "period", "partner", "direction", "chapter", unique=True),
    )

    period = Column(String(10), nullable=False)         # "2025" (Comtrade es anual)
    partner = Column(String(80), nullable=False)        # nombre del socio, p. ej. "China"
    partner_code = Column(String(8), nullable=True)     # M49, para re-consultar sin ambigüedad
    direction: Any = Column(Enum(TradeDirection), nullable=False)
    chapter = Column(String(2), nullable=False)         # capítulo HS de 2 dígitos
    value = Column(Float, nullable=True)                # USD millones; NULL = ausente
    # Lineage
    source = Column(String(40), nullable=True)
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
