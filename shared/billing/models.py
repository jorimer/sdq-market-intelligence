"""Persistencia del tarifario gestionado (monetización Fase B1).

Transversal (vive en ``shared/billing``, no en un módulo de sector). El precio deja de
ser una constante en código y pasa a ser una **entidad de primera clase administrable**:
cada ``Tariff`` es el precio de un ``sku`` con **vigencia por fechas** (``effective_from`` /
``effective_to``). El "precio vigente" a una fecha se resuelve eligiendo la fila activa
cuya ventana contiene esa fecha (ver ``shared/billing/tariffs.py``).

Parity SQLite↔Postgres: ``Numeric`` para el monto (no Float, que pierde centavos),
``DateTime`` naive (la comparación de vigencia se hace contra un UTC-naive del lado SQL),
``String`` acotado.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    true,
)

from shared.database.base import Base, UUIDMixin


class Tariff(UUIDMixin, Base):
    """Precio vigente de un ``sku`` durante una ventana de fechas.

    ``sku`` identifica qué se cobra (independiente del proveedor de pago):
    ``insight`` (suscripción pro, plataforma-wide), ``deep_dive:{sector}`` (compra puntual
    de un sector) o ``special:{slug}`` (informe especial cotizado a medida).

    Vigencia: ``effective_from`` (cuándo entra a regir) y ``effective_to`` (None = abierto).
    Publicar un precio nuevo = insertar otra fila (típicamente con ``effective_from`` futuro);
    no se edita ni borra el histórico (auditable). Revocar/retirar = ``active=False``.
    """

    __tablename__ = "tariff"

    sku = Column(String(80), nullable=False)
    currency = Column(String(3), nullable=False, server_default="USD")  # ISO 4217
    amount = Column(Numeric(12, 2), nullable=False)  # monto en la moneda, 2 decimales

    effective_from = Column(DateTime, nullable=False)  # naive UTC: cuándo entra a regir
    effective_to = Column(DateTime, nullable=True)     # naive UTC; None = abierto
    active = Column(Boolean, nullable=False, default=True, server_default=true())

    label = Column(String(120), nullable=True)  # nombre visible (p.ej. del informe especial)
    note = Column(String(255), nullable=True)   # motivo / referencia interna
    created_by = Column(String, ForeignKey("users.id"), nullable=True)  # admin que la publicó

    __table_args__ = (
        Index("ix_tariff_sku", "sku"),
        # Lookup del precio vigente: por sku + ventana de fechas.
        Index("ix_tariff_sku_window", "sku", "effective_from"),
    )


class BillingEvent(UUIDMixin, Base):
    """Evento de webhook YA procesado — idempotencia de la pasarela (Fase 3).

    El proveedor puede reenviar el mismo evento; procesarlo dos veces duplicaría accesos.
    Antes de aplicar un webhook se inserta ``(provider, event_id)`` único: si ya existe, se
    ignora. ``kind`` guarda el tipo normalizado (order_paid / subscription_*) para auditar."""

    __tablename__ = "billing_event"

    provider = Column(String(20), nullable=False)     # paypal | azul
    event_id = Column(String(128), nullable=False)    # id del evento en el proveedor
    kind = Column(String(40), nullable=True)          # tipo normalizado aplicado
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("uq_billing_event", "provider", "event_id", unique=True),
    )
