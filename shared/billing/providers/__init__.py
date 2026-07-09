"""Fábrica del proveedor de pago activo (Fase 3).

Hoy PayPal (primario); Azul entrará detrás del mismo puerto ``BillingProvider``. El
proveedor se construye con la config de la plataforma (credenciales encriptadas)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from shared.billing.providers.base import (  # noqa: F401 — re-export del puerto
    BillingProvider,
    Checkout,
    NormalizedEvent,
    ProviderError,
    ProviderNotConfigured,
)


def get_provider(db: Session, name: str = "paypal") -> BillingProvider:
    """El adaptador del proveedor *name* con la config actual. Hoy solo PayPal."""
    from shared.billing.providers.paypal import PayPalProvider
    from shared.settings.service import get_paypal_config

    if name == "paypal":
        return PayPalProvider(get_paypal_config(db))
    raise ProviderError(f"Proveedor de pago desconocido: '{name}'.")
