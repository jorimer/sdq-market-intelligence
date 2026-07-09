"""Motor de impuesto sobre la venta (ITBIS RD) — desglose subtotal / impuesto / total.

El precio del tarifario (``Tariff.amount``) es el **subtotal pre-impuesto**; este módulo le
suma el impuesto configurado y devuelve el desglose exacto al centavo. Regla de la matriz
fiscal SDQ (config en ``shared/settings/service.py:get_tax_config``):

- Cliente de RD (``home_country``): se aplica el ITBIS (18% por defecto).
- Cliente del exterior + ``exempt_foreign``: **exportación de servicios → exento** (0%).
- ``enabled=False``: no se aplica impuesto (todo va como subtotal).

A PayPal se le pasa el **total** (subtotal + impuesto); la factura al cliente lo desglosa.
Todo en ``Decimal`` con redondeo HALF_UP a 2 decimales (el dinero es sagrado: cuadra al
centavo, moneda explícita en el que llama).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

_CENTS = Decimal("0.01")

# Base legal de la exención (exportación de servicios). Texto para la factura/UI.
EXEMPT_REASON_FOREIGN = "Exportación de servicios — exento de ITBIS (cliente del exterior)."


def _q(value: Decimal) -> Decimal:
    """Cuantiza a centavos con redondeo bancario estándar RD (HALF_UP)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 — cualquier entrada no numérica → 0
        return Decimal("0")


def normalize_country(country: Optional[str]) -> str:
    """ISO-2 en mayúsculas; vacío/None → 'DO' (default conservador: tributa, no exime)."""
    c = (country or "").strip().upper()
    return c[:2] if c else "DO"


@dataclass(frozen=True)
class TaxBreakdown:
    """Desglose de un cobro. Montos como string decimal (2 dec) para exactitud en JSON."""

    currency: str
    subtotal: str        # precio del tarifario (pre-impuesto)
    rate_pct: str        # tasa aplicada, p.ej. "18" o "0"
    tax: str             # monto del impuesto
    total: str           # subtotal + impuesto (lo que se le pasa a PayPal)
    label: str           # etiqueta del impuesto, p.ej. "ITBIS"
    exempt: bool         # True si se aplicó una exención (rate 0 por regla, no por enabled)
    exempt_reason: Optional[str]
    country: str         # ISO-2 del cliente que definió el trato fiscal

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_tax(subtotal: Any, *, currency: str, country: Optional[str],
                config: Dict[str, Any]) -> TaxBreakdown:
    """Computa el desglose de un cobro dado el subtotal, la moneda, el país del cliente y la
    config de impuesto (``get_tax_config``). No toca la base de datos."""
    sub = _q(_to_decimal(subtotal))
    ccy = (currency or "USD").upper()
    cc = normalize_country(country)
    home = normalize_country(config.get("home_country") or "DO")
    label = str(config.get("label") or "ITBIS")
    enabled = bool(config.get("enabled", True))
    exempt_foreign = bool(config.get("exempt_foreign", True))
    rate = _to_decimal(config.get("rate") or "0")

    exempt = False
    exempt_reason: Optional[str] = None
    if not enabled:
        rate = Decimal("0")
    elif exempt_foreign and cc != home:
        rate = Decimal("0")
        exempt = True
        exempt_reason = EXEMPT_REASON_FOREIGN

    tax = _q(sub * rate / Decimal("100"))
    total = _q(sub + tax)
    return TaxBreakdown(
        currency=ccy,
        subtotal=format(sub, "f"),
        rate_pct=format(rate.normalize(), "f") if rate == rate.to_integral() else format(rate, "f"),
        tax=format(tax, "f"),
        total=format(total, "f"),
        label=label,
        exempt=exempt,
        exempt_reason=exempt_reason,
        country=cc,
    )


def compute_tax_from_total(total: Any, *, currency: str, country: Optional[str],
                           config: Dict[str, Any]) -> TaxBreakdown:
    """Desglose partiendo del TOTAL ya cobrado (no del subtotal): back-deriva
    ``subtotal = total / (1 + tasa)``. Fallback honesto para facturar cuando sólo se conoce
    el bruto que cobró el proveedor (p.ej. el precio del tarifario cambió tras el checkout)."""
    tot = _q(_to_decimal(total))
    cc = normalize_country(country)
    home = normalize_country(config.get("home_country") or "DO")
    enabled = bool(config.get("enabled", True))
    exempt_foreign = bool(config.get("exempt_foreign", True))
    rate = _to_decimal(config.get("rate") or "0")
    if not enabled or (exempt_foreign and cc != home):
        rate = Decimal("0")
    subtotal = _q(tot / (Decimal("1") + rate / Decimal("100"))) if rate != 0 else tot
    return compute_tax(subtotal, currency=currency, country=country, config=config)


def quote_for(db: Session, *, subtotal: Any, currency: str,
              country: Optional[str]) -> TaxBreakdown:
    """Atajo: lee la config de impuesto de la BD y computa el desglose. Lo usan el endpoint
    de cotización (``/checkout/quote``), el checkout y la factura para hablar el mismo idioma."""
    from shared.settings.service import get_tax_config

    return compute_tax(subtotal, currency=currency, country=country, config=get_tax_config(db))
