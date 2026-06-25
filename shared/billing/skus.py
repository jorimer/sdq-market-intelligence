"""SKUs del tarifario — qué se cobra, independiente del proveedor de pago.

Un SKU es un string canónico que el tarifario (``Tariff.sku``) y, en B3, el checkout y el
webhook comparten como vocabulario común. Tres familias:

- ``insight`` — la suscripción pro (Insight), plataforma-wide. Mapea a ``AccessTier.pro``.
- ``deep_dive:{sector}`` — la compra puntual de un Deep Dive de un sector del catálogo.
  Mapea a un entitlement por-producto ``(sector, deep_dive)``.
- ``special:{slug}`` — un informe especial cotizado a medida (slug libre kebab-case).

El SKU NO conoce al proveedor: PayPal/Azul exponen su propio id de plan/variante, que en
B3 se mapeará a un SKU. Acá solo se valida la forma y se referencia el catálogo de sectores.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from shared.products.registry import CATALOG_BY_KEY
from shared.products.tiers import ProductTier

SKU_INSIGHT = "insight"
_DEEP_DIVE_PREFIX = "deep_dive:"
_SPECIAL_PREFIX = "special:"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class SkuError(ValueError):
    """SKU mal formado o que referencia un sector fuera del catálogo."""


def deep_dive_sku(sector_key: str) -> str:
    """SKU de la compra puntual de un Deep Dive de un sector."""
    return f"{_DEEP_DIVE_PREFIX}{sector_key}"


def special_sku(slug: str) -> str:
    """SKU de un informe especial (cotización a medida)."""
    return f"{_SPECIAL_PREFIX}{slug}"


def parse_sku(sku: str) -> Tuple[str, Optional[str]]:
    """Descompone un SKU en ``(kind, ref)``. ``kind`` ∈ {insight, deep_dive, special};
    ``ref`` es el sector (deep_dive), el slug (special) o ``None`` (insight).
    Levanta ``SkuError`` si la forma es inválida (no valida existencia del sector: eso lo
    hace ``validate_sku``)."""
    if sku == SKU_INSIGHT:
        return ("insight", None)
    if sku.startswith(_DEEP_DIVE_PREFIX):
        ref = sku[len(_DEEP_DIVE_PREFIX):]
        if not ref:
            raise SkuError("SKU deep_dive sin sector.")
        return ("deep_dive", ref)
    if sku.startswith(_SPECIAL_PREFIX):
        ref = sku[len(_SPECIAL_PREFIX):]
        if not _SLUG_RE.match(ref):
            raise SkuError(f"Slug de informe especial inválido: '{ref}'.")
        return ("special", ref)
    raise SkuError(
        f"SKU inválido '{sku}'. Use 'insight', 'deep_dive:{{sector}}' o 'special:{{slug}}'.")


def validate_sku(sku: str) -> Tuple[str, Optional[str]]:
    """Como ``parse_sku`` pero además valida que un ``deep_dive`` referencie un sector
    real del catálogo de productos. Devuelve ``(kind, ref)``."""
    kind, ref = parse_sku(sku)
    if kind == "deep_dive" and ref not in CATALOG_BY_KEY:
        raise SkuError(f"Sector '{ref}' no está en el catálogo de productos.")
    return kind, ref


def entitlement_for_sku(sku: str) -> Optional[Tuple[str, ProductTier]]:
    """Si el SKU corresponde a una compra por-producto (Deep Dive), devuelve el
    ``(sector_key, ProductTier.deep_dive)`` que el webhook otorgará vía
    ``grant_entitlement``. Para ``insight`` (suscripción → tier) o ``special`` devuelve
    ``None`` (no es un entitlement por-producto)."""
    kind, ref = validate_sku(sku)
    if kind == "deep_dive" and ref is not None:
        return (ref, ProductTier.deep_dive)
    return None
