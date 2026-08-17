"""Puerto ``BillingProvider`` — abstracción de la pasarela de pago (Fase 3).

El resto de la plataforma (endpoints de checkout, webhook) habla SOLO con este puerto; el
adaptador concreto (PayPal, luego Azul) implementa la interfaz. Anti-Frankenstein: el puerto
no conoce modules.*; el webhook mapea el ``NormalizedEvent`` al modelo de acceso ya
existente (``apply_subscription`` / ``grant_entitlement`` / ``expire_subscription``).

Nada de esto muta ``User.tier``: una suscripción/entitlement es su propio eje de acceso.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class ProviderError(RuntimeError):
    """Fallo del proveedor (HTTP, parsing, etc.)."""


class ProviderNotConfigured(ProviderError):
    """El proveedor no tiene credenciales cargadas → no se puede cobrar todavía."""


@dataclass(frozen=True)
class Checkout:
    """Resultado de iniciar un checkout: a dónde mandar al usuario a aprobar el pago."""

    approval_url: str
    provider_ref: str  # id de la orden/suscripción en el proveedor


@dataclass(frozen=True)
class NormalizedEvent:
    """Un evento de webhook ya normalizado (agnóstico del proveedor).

    ``kind``:
      - ``subscription_active``   → conceder/renovar la suscripción (tier).
      - ``subscription_renewed``  → COBRO recurrente: extiende el período y factura aparte.
      - ``subscription_cancelled``/``subscription_expired`` → cortar la suscripción.
      - ``order_paid``            → conceder el entitlement por-producto (Deep Dive).
      - ``payment_refunded``      → revertir el cobro (nota de crédito + corte de acceso).
    ``sku`` (order) o ``tier`` (subscription) + ``user_id`` vienen del ``custom_id`` que el
    checkout embebió. ``provider_ref`` es el id de la suscripción/orden en el proveedor.
    """

    event_id: str          # id único del evento (idempotencia)
    kind: str
    provider_ref: str
    user_id: Optional[str] = None
    tier: Optional[str] = None
    sku: Optional[str] = None
    period_end: Optional[str] = None  # ISO, fin del período de la suscripción
    # Para facturar (Fase 4): el intervalo de la suscripción y/o el plan_id del proveedor
    # (permite resolver el intervalo desde el mapa de planes) y el bruto realmente cobrado
    # por el proveedor (reconciliación contra el desglose que computa la plataforma).
    plan_id: Optional[str] = None
    interval: Optional[str] = None
    amount_gross: Optional[str] = None
    amount_currency: Optional[str] = None
    # Id del COBRO puntual dentro de una suscripción (el "sale" de PayPal). Distingue el
    # cobro del mes 2 del cobro del mes 1: sin esto los dos comparten el id de la suscripción
    # y la idempotencia de la factura descartaría la renovación como si fuera un duplicado.
    charge_ref: Optional[str] = None


class BillingProvider(Protocol):
    """Lo que la plataforma le pide a una pasarela de pago."""

    name: str

    def is_configured(self) -> bool:
        """¿Hay credenciales para operar? Si no, el checkout responde 'no configurado'."""
        ...

    def create_order_checkout(self, *, sku: str, amount: str, currency: str, user_id: str,
                              return_url: str, cancel_url: str,
                              subtotal: Optional[str] = None, tax: Optional[str] = None) -> Checkout:
        """Compra puntual (Deep Dive): crea la orden por el TOTAL (subtotal + impuesto) y
        devuelve el link de aprobación. ``subtotal``/``tax`` alimentan el desglose del proveedor."""
        ...

    def create_subscription_checkout(self, *, sku: str, interval: str, user_id: str,
                                     return_url: str, cancel_url: str,
                                     tax_percentage: Optional[str] = None) -> Checkout:
        """Suscripción (por-sector o bundle): crea la suscripción por su plan y devuelve el
        link. ``tax_percentage`` aplica el impuesto sobre el precio base del plan."""
        ...

    def cancel_subscription(self, subscription_id: str, *, reason: str = "") -> None:
        """Cancela una suscripción en el proveedor (a pedido del cliente). El proveedor emite
        luego el webhook de cancelación que corta el acceso."""
        ...

    def get_subscription(self, subscription_id: str) -> dict:
        """Lee el estado de una suscripción (para activar en el retorno sin depender del
        webhook). Devuelve status/plan/interval/user/sku/período/monto normalizados."""
        ...

    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        """Verifica la firma del webhook contra el proveedor. False = rechazar."""
        ...

    def parse_event(self, payload: dict) -> Optional[NormalizedEvent]:
        """Traduce el payload del webhook a un ``NormalizedEvent``, o None si no interesa."""
        ...
