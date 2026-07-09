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
    false,
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
    # Periodicidad del cobro: once (compra puntual) | monthly | annual. El precio vigente se
    # resuelve por (sku, interval); el anual suele ser el mensual×12 con descuento.
    interval = Column(String(10), nullable=False, server_default="once")
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
        # Lookup del precio vigente: por sku + intervalo + ventana de fechas.
        Index("ix_tariff_sku_window", "sku", "interval", "effective_from"),
    )


class BillingTransaction(UUIDMixin, Base):
    """Un cobro facturable — el registro contable de una compra puntual o el alta/renovación
    de una suscripción (monetización Fase 4). Persiste el DESGLOSE fiscal al centavo:
    ``subtotal`` (precio del tarifario, pre-impuesto) + ``tax_amount`` (ITBIS o exento) =
    ``total`` (lo que se le cobró a PayPal). Es la fuente de la **factura desglosada** al
    cliente (``shared/billing/invoice.py``) y queda para auditoría.

    Lo crea el webhook al confirmar el pago (``order_paid`` / ``subscription_active``); es
    idempotente vía el ``BillingEvent`` que lo acompaña (un mismo evento no duplica cobro).
    Provider-agnóstico en el modelo (hoy sólo PayPal). ``invoice_number`` es un correlativo
    interno legible (no es un NCF de la DGII — ese es un dato fiscal que el dueño debe cargar).
    """

    __tablename__ = "billing_transaction"

    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sku = Column(String(80), nullable=False)
    kind = Column(String(20), nullable=False)              # order | subscription
    provider = Column(String(20), nullable=False)          # paypal | azul
    provider_ref = Column(String(128), nullable=True)      # order id / subscription id
    # Evento del proveedor que originó el cobro (idempotencia + traza al BillingEvent).
    event_id = Column(String(128), nullable=True)

    currency = Column(String(3), nullable=False, server_default="USD")
    subtotal = Column(Numeric(12, 2), nullable=False)      # pre-impuesto (precio tarifario)
    tax_rate = Column(Numeric(5, 2), nullable=False, server_default="0")   # % aplicado
    tax_amount = Column(Numeric(12, 2), nullable=False, server_default="0")
    total = Column(Numeric(12, 2), nullable=False)         # subtotal + impuesto (cobrado)
    tax_label = Column(String(40), nullable=True)          # p.ej. "ITBIS"
    tax_exempt = Column(Boolean, nullable=False, default=False, server_default=false())
    country = Column(String(2), nullable=True)             # país de facturación del cliente

    invoice_number = Column(String(40), nullable=True)     # correlativo interno (no NCF)
    status = Column(String(20), nullable=False, server_default="paid")  # paid | refunded
    note = Column(String(255), nullable=True)

    # ── e-CF / e-NCF (DGII) — listo para la integración de factura electrónica ──
    # Tipo de e-CF previsto (RD con RNC=31 crédito fiscal · RD consumo=32 · exterior=46
    # exportación). El resto se llena cuando se emite el e-CF contra los web services de la
    # DGII (certificado digital + secuencia e-NCF autorizada). Nullable = aún no emitido.
    encf_type = Column(String(2), nullable=True)           # 31 | 32 | 46 …
    encf_number = Column(String(19), nullable=True)        # e-NCF asignado por la DGII
    encf_status = Column(String(20), nullable=True)        # pending | issued | accepted | rejected
    encf_trackid = Column(String(40), nullable=True)       # TrackID del acuse (ACECF)
    encf_security_code = Column(String(12), nullable=True) # código de seguridad (representación impresa)
    encf_signed_at = Column(DateTime, nullable=True)       # fecha/hora de la firma digital

    __table_args__ = (
        Index("ix_billing_transaction_user", "user_id"),
        # Un evento del proveedor produce a lo sumo una transacción (idempotencia dura).
        Index("uq_billing_transaction_event", "provider", "event_id", unique=True),
        Index("uq_billing_transaction_invoice", "invoice_number", unique=True),
    )


class EncfSequence(UUIDMixin, Base):
    """Rango de secuencia e-NCF autorizado por la DGII para un tipo de e-CF (Fase e-CF).

    El e-NCF tiene el formato ``E`` + tipo (2 díg.) + secuencia (10 díg.) = 13 caracteres
    (p.ej. ``E310000000001``). La DGII autoriza un RANGO por tipo (``range_from``..``range_to``)
    con una fecha de vencimiento; el emisor asigna correlativos consecutivos desde ``current``.
    ``allocate_next`` toma el próximo, controla vencimiento y agotamiento. Un tipo puede tener
    varias filas históricas; se asigna desde la activa, no vencida y con cupo."""

    __tablename__ = "encf_sequence"

    ecf_type = Column(String(2), nullable=False)      # 31 | 32 | 46 …
    range_from = Column(Numeric(12, 0), nullable=False)  # inicio del rango autorizado
    range_to = Column(Numeric(12, 0), nullable=False)    # fin del rango (inclusive)
    current = Column(Numeric(12, 0), nullable=False)     # próximo correlativo a asignar
    expires_at = Column(DateTime, nullable=True)         # vencimiento de la secuencia (DGII)
    active = Column(Boolean, nullable=False, default=True, server_default=true())
    note = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_encf_sequence_type", "ecf_type"),
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
