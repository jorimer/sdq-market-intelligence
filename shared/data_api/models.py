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
    # 512: guarda el mismo ``asset.key`` ("{sector}:{kind}:{code}") que el ledger; con
    # códigos BCRD/SIB largos, 255 desbordaba y tumbaba el commit de la llamada servida.
    asset_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
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


class ApiAssetLedger(Base, UUIDMixin):
    """Cuándo apareció y cuándo dejó de estar cada activo del catálogo.

    Sin esto, la auto-extensión es invisible para quien automatiza: el inventario crece
    solo, pero el cliente no tiene forma de saber QUÉ es nuevo desde su última corrida
    (y enterarse por correo es justo lo que la auto-extensión venía a evitar).

    Se actualiza al construir el manifiesto — el mismo recorrido que ya descubre los
    activos registra lo que ve. Un activo que deja de aparecer NO se borra: se marca
    ``retired_at``, porque para un cliente la baja es tan informativa como el alta.
    """

    __tablename__ = "data_api_asset_ledger"

    # 512, no 255/180: la clave y el code copian ``mm_series.series_code`` (VARCHAR 255,
    # códigos jerárquicos del motor Excel BCRD/SIB) y la clave le antepone
    # "{sector}:{kind}:" (~15 chars). 180 desbordaba en Postgres y tumbaba el batch entero.
    asset_key: Mapped[str] = mapped_column(String(512), nullable=False)   # "macro:series:x"
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    sector_key: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(512), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # None = sigue vivo. Se rellena cuando el activo desaparece del manifiesto.
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Última exposición conocida: permite explicar una baja ("pasó a cuarentena por X").
    last_exposed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    last_quarantine: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("asset_key", name="uq_data_api_asset_ledger_key"),
        Index("ix_data_api_asset_ledger_seen", "first_seen_at", "retired_at"),
    )


class ApiWebhook(Base, UUIDMixin):
    """Suscripción de un cliente a los eventos de "hay dato nuevo".

    Convierte el consumo de sondeo en consumo por aviso: en vez de que PMS pregunte cada
    hora si el BCRD publicó, se le avisa cuando el snapshot se recalcula. El aviso NO
    lleva el dato — solo dice qué cambió; el cliente vuelve por la API con su llave. Así
    el webhook no se convierte en un segundo canal de datos con sus propios permisos.
    """

    __tablename__ = "data_api_webhook"

    api_key_id: Mapped[str] = mapped_column(
        String, ForeignKey("data_api_key.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Secreto con el que se firma cada envío (HMAC-SHA256). El receptor verifica que el
    # POST viene de nosotros: una URL de webhook es pública por naturaleza.
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    events: Mapped[str] = mapped_column(String(255), nullable=False)  # CSV; "*" = todos
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Cortafuegos: tras N fallos seguidos el webhook se desactiva solo. Un endpoint
    # muerto no debe costarnos un intento por evento para siempre.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        Index("ix_data_api_webhook_key", "api_key_id"),
    )


class ApiWebhookDelivery(Base, UUIDMixin):
    """Un intento de entrega. Sin esto, "no me llegó el aviso" no se puede diagnosticar."""

    __tablename__ = "data_api_webhook_delivery"

    webhook_id: Mapped[str] = mapped_column(
        String, ForeignKey("data_api_webhook.id"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_data_api_webhook_delivery_hook", "webhook_id", "attempted_at"),
    )
