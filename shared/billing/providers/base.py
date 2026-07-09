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
      - ``subscription_cancelled``/``subscription_expired`` → cortar la suscripción.
      - ``order_paid``            → conceder el entitlement por-producto (Deep Dive).
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


class BillingProvider(Protocol):
    """Lo que la plataforma le pide a una pasarela de pago."""

    name: str

    def is_configured(self) -> bool:
        """¿Hay credenciales para operar? Si no, el checkout responde 'no configurado'."""
        ...

    def create_order_checkout(self, *, sku: str, amount: str, currency: str, user_id: str,
                              return_url: str, cancel_url: str) -> Checkout:
        """Compra puntual (Deep Dive): crea la orden y devuelve el link de aprobación."""
        ...

    def create_subscription_checkout(self, *, tier: str, user_id: str,
                                     return_url: str, cancel_url: str) -> Checkout:
        """Suscripción (plan Insight/Enterprise): crea la suscripción y devuelve el link."""
        ...

    def verify_webhook(self, *, headers: dict, body: bytes) -> bool:
        """Verifica la firma del webhook contra el proveedor. False = rechazar."""
        ...

    def parse_event(self, payload: dict) -> Optional[NormalizedEvent]:
        """Traduce el payload del webhook a un ``NormalizedEvent``, o None si no interesa."""
        ...
