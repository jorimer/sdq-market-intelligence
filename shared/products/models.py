"""Persistencia del monitor de productos: readiness calculado + activación pública.

Transversal (vive en ``shared/``, no en un módulo de sector). PK UUID, parity
SQLite↔Postgres (Float para scores, JSON para linaje, String acotado).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    false,
    true,
)

from shared.database.base import Base, UUIDMixin


class ProductReadiness(UUIDMixin, Base):
    """Último readiness calculado de un (sector, nivel). Recalculado por evento + manual."""

    __tablename__ = "product_readiness"

    sector_key = Column(String(40), nullable=False)
    tier = Column(String(20), nullable=False)

    g1 = Column(Float, nullable=False, default=0.0)  # Data
    g2 = Column(Float, nullable=False, default=0.0)  # Motor
    g3 = Column(Float, nullable=False, default=0.0)  # Narrativa
    g4 = Column(Float, nullable=False, default=0.0)  # Plantilla
    g5 = Column(Float, nullable=False, default=0.0)  # Validación
    readiness = Column(Float, nullable=False, default=0.0)  # 0–1

    # Linaje: cada gate apunta a la señal que lo originó (trazabilidad).
    detail = Column(JSON, nullable=True)
    computed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("sector_key", "tier", name="uq_product_readiness_sector_tier"),
        Index("ix_product_readiness_sector", "sector_key"),
    )


class SampleGrant(UUIDMixin, Base):
    """Registro de muestra descargada: un usuario puede bajar UNA muestra por
    (sector, nivel). La unicidad ``(user_id, sector_key, tier)`` enforca el límite
    "una única vez" por producto/nivel (mecanismo de conversión)."""

    __tablename__ = "sample_grant"

    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sector_key = Column(String(40), nullable=False)
    tier = Column(String(20), nullable=False)
    downloaded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "sector_key", "tier", name="uq_sample_grant_user_sector_tier"),
        Index("ix_sample_grant_user", "user_id"),
    )


class ProductEntitlement(UUIDMixin, Base):
    """Acceso por-producto otorgado a un usuario, **además** de su tier de suscripción
    (monetización Fase B). Modela la "compra puntual" de un (sector, nivel) —típicamente
    un Deep Dive on-demand— que desbloquea ese producto para el usuario aunque su tier no
    lo alcance. ``can_access`` lo honra (tier OR entitlement). Provider-agnóstico: en B0
    lo otorga el admin a mano (cobro fuera de plataforma); en B1 lo crea el webhook de
    pago. Soporta expiración opcional (``expires_at`` None = perpetuo) y revocación
    (``active``)."""

    __tablename__ = "product_entitlement"

    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sector_key = Column(String(40), nullable=False)
    tier = Column(String(20), nullable=False)
    source = Column(String(20), nullable=False, server_default="manual")  # manual | order
    granted_by = Column(String, ForeignKey("users.id"), nullable=True)    # admin que otorgó
    granted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)                          # None = perpetuo
    active = Column(Boolean, nullable=False, default=True, server_default=true())
    note = Column(String(255), nullable=True)                            # ref de orden / motivo

    __table_args__ = (
        Index("ix_product_entitlement_user", "user_id"),
        Index("ix_product_entitlement_lookup", "user_id", "sector_key", "tier"),
    )


class ProductActivation(UUIDMixin, Base):
    """Estado de activación de ACCESO PÚBLICO de un (sector, nivel).

    Separado del readiness: un producto puede estar cableado y operativo internamente
    (readiness alto) sin estar activado. La activación es manual/explícita y gated por
    el umbral del nivel.
    """

    __tablename__ = "product_activation"

    sector_key = Column(String(40), nullable=False)
    tier = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=False, server_default=false())
    activated_by = Column(String, ForeignKey("users.id"), nullable=True)
    activated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("sector_key", "tier", name="uq_product_activation_sector_tier"),
        Index("ix_product_activation_sector", "sector_key"),
    )
