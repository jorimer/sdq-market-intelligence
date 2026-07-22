"""Tablas de la Data API — llaves de cliente y bitácora de uso.

Doctrina de la llave (docs/SPEC_API_DATOS_PROPIETARIOS.md §5): el secreto NUNCA se
guarda; se guarda su hash y un ``prefix`` visible que identifica la llave en la UI y en
la bitácora. El scope NO se declara a mano: la llave hereda los entitlements de su
usuario dueño (``shared/products/access``), de modo que dar/quitar acceso comercial y
dar/quitar acceso de API son la misma operación y no pueden divergir.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base, UUIDMixin


class ApiKey(UUIDMixin, Base):
    """Credencial máquina-a-máquina de un consumidor de la Data API.

    Declarada con el estilo TIPADO de SQLAlchemy 2.0 (``Mapped`` / ``mapped_column``), a
    diferencia del resto del repo, que usa el estilo legacy ``Column``. Es deliberado:
    con ``Column`` el checker ve ``Column[str]`` donde el código usa un ``str``, y toda
    lectura o asignación genera ruido de tipos (el baseline del repo carga ~1300 de esos).
    Código nuevo no debería sumar deuda que ya se está pagando.
    """

    __tablename__ = "data_api_key"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)   # "SDQ-PMS · producción"
    # Identificador visible de la llave (va en la respuesta y en la bitácora). El
    # secreto completo se muestra UNA sola vez, al crearla.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 — ver keys.py
    # Marca de agua lógica: viaja en cada respuesta servida con esta llave, para poder
    # rastrear el origen de un payload redistribuido sin autorización.
    client_ref: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    # Para QUÉ usa el dato este consumidor. No es una etiqueta administrativa: decide si
    # puede recibir series de fuentes con licencia no-comercial o share-alike.
    #   "internal" — insumo de análisis propio; el dato no sale hacia terceros. Es el
    #                caso de SDQ-PMS: interpreta el mercado con esto, no lo reexpide.
    #   "external" — el consumidor podría reexponer el dato. Solo recibe lo que la
    #                licencia de origen permite redistribuir.
    # Default "external" a propósito: lo restrictivo se asume, lo permisivo se declara.
    usage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="external", server_default="external"
    )

    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # None = sin tope mensual (uso interno del grupo). Un cliente externo SIEMPRE lleva
    # tope: sin cuota no hay forma de distinguir uso legítimo de vaciado del catálogo.
    quota_per_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # None = sin caducidad
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("prefix", name="uq_data_api_key_prefix"),
        Index("ix_data_api_key_user", "user_id"),
    )


class ApiUsage(UUIDMixin, Base):
    """Una llamada servida (o rechazada). Insumo de cuota, facturación y soporte.

    Se registra TAMBIÉN lo rechazado (429, 402, 404): un patrón de rechazos es la señal
    más temprana de que alguien está barriendo el catálogo o de que un cliente quedó mal
    configurado.
    """

    __tablename__ = "data_api_usage"

    api_key_id: Mapped[str] = mapped_column(
        String, ForeignKey("data_api_key.id"), nullable=False
    )
    resource: Mapped[str] = mapped_column(String(60), nullable=False)  # "catalog" | "series" | …
    asset_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    as_of: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Período de cuota "YYYY-MM" desnormalizado: la cuota mensual se cuenta por índice
    # sobre esta columna en vez de por función de fecha, que en SQLite y Postgres se
    # escribe distinto (parity dev↔prod).
    quota_period: Mapped[str] = mapped_column(String(7), nullable=False)

    __table_args__ = (
        Index("ix_data_api_usage_key_period", "api_key_id", "quota_period"),
        Index("ix_data_api_usage_key_time", "api_key_id", "requested_at"),
    )
