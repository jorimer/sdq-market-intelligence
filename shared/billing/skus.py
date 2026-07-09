"""SKUs del tarifario — qué se cobra, independiente del proveedor de pago (modelo v2).

Un SKU es un string canónico que el tarifario (``Tariff.sku``), el checkout y el webhook
comparten. Familias (POR SECTOR + bundles, según el estudio de pricing):

- ``insight:{sector}``  — suscripción al Insight de UN sector (mensual/anual).
- ``deep_dive:{sector}``— compra puntual de un Deep Dive de un sector.
- ``all_access``        — suscripción bundle: el Insight de TODOS los sectores.
- ``enterprise``        — suscripción total: todo el catálogo (Insight + Deep Dive).
- ``special:{slug}``    — informe especial cotizado a medida (una vez).

Cada SKU concede acceso a uno o más (sector, nivel) — ver :func:`sku_grants` — que
``can_access`` compone. Las suscripciones tienen **intervalo** (mensual/anual); las compras
puntuales, intervalo ``once``.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from shared.products.registry import CATALOG_BY_KEY, PRODUCT_CATALOG
from shared.products.tiers import ProductTier

_DEEP_DIVE_PREFIX = "deep_dive:"
_INSIGHT_PREFIX = "insight:"
_SPECIAL_PREFIX = "special:"
SKU_ALL_ACCESS = "all_access"
SKU_ENTERPRISE = "enterprise"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Intervalos de cobro.
INTERVAL_ONCE = "once"
INTERVAL_MONTHLY = "monthly"
INTERVAL_ANNUAL = "annual"
VALID_INTERVALS = {INTERVAL_ONCE, INTERVAL_MONTHLY, INTERVAL_ANNUAL}

# Orden de niveles (para "un grant de nivel N cubre los niveles ≤ N" en un sector).
_LEVEL_RANK = {ProductTier.pulse.value: 0, ProductTier.insight.value: 1, ProductTier.deep_dive.value: 2}


class SkuError(ValueError):
    """SKU mal formado o que referencia un sector fuera del catálogo."""


def deep_dive_sku(sector_key: str) -> str:
    return f"{_DEEP_DIVE_PREFIX}{sector_key}"


def insight_sku(sector_key: str) -> str:
    return f"{_INSIGHT_PREFIX}{sector_key}"


def special_sku(slug: str) -> str:
    return f"{_SPECIAL_PREFIX}{slug}"


def parse_sku(sku: str) -> Tuple[str, Optional[str]]:
    """Descompone un SKU en ``(kind, ref)``. ``kind`` ∈ {insight, deep_dive, all_access,
    enterprise, special}; ``ref`` = sector (insight/deep_dive), slug (special) o None."""
    if sku == SKU_ALL_ACCESS:
        return ("all_access", None)
    if sku == SKU_ENTERPRISE:
        return ("enterprise", None)
    for prefix, kind in ((_INSIGHT_PREFIX, "insight"), (_DEEP_DIVE_PREFIX, "deep_dive")):
        if sku.startswith(prefix):
            ref = sku[len(prefix):]
            if not ref:
                raise SkuError(f"SKU {kind} sin sector.")
            return (kind, ref)
    if sku.startswith(_SPECIAL_PREFIX):
        ref = sku[len(_SPECIAL_PREFIX):]
        if not _SLUG_RE.match(ref):
            raise SkuError(f"Slug de informe especial inválido: '{ref}'.")
        return ("special", ref)
    raise SkuError(
        f"SKU inválido '{sku}'. Use 'insight:{{sector}}', 'deep_dive:{{sector}}', "
        f"'all_access', 'enterprise' o 'special:{{slug}}'.")


def validate_sku(sku: str) -> Tuple[str, Optional[str]]:
    """Como ``parse_sku`` pero valida que un sector referenciado exista en el catálogo."""
    kind, ref = parse_sku(sku)
    if kind in ("insight", "deep_dive") and ref not in CATALOG_BY_KEY:
        raise SkuError(f"Sector '{ref}' no está en el catálogo de productos.")
    return kind, ref


def is_subscription_sku(sku: str) -> bool:
    """¿El SKU es una suscripción recurrente (vs compra puntual)?"""
    kind, _ = parse_sku(sku)
    return kind in ("insight", "all_access", "enterprise")


def allowed_intervals(sku: str) -> List[str]:
    """Intervalos válidos del SKU: mensual+anual para suscripciones, once para compra puntual."""
    return [INTERVAL_MONTHLY, INTERVAL_ANNUAL] if is_subscription_sku(sku) else [INTERVAL_ONCE]


def sku_grants(sku: str) -> List[Tuple[str, str]]:
    """Qué (scope, nivel) concede el SKU. ``scope`` = sector_key o ``"*"`` (todos). Un grant
    de nivel N en un scope cubre los niveles ≤ N de ese scope (deep_dive ⊇ insight ⊇ pulse)."""
    kind, ref = parse_sku(sku)
    if kind == "deep_dive":
        return [(ref, ProductTier.deep_dive.value)]
    if kind == "insight":
        return [(ref, ProductTier.insight.value)]
    if kind == "all_access":
        return [("*", ProductTier.insight.value)]
    if kind == "enterprise":
        return [("*", ProductTier.deep_dive.value)]
    return []  # special: sin grant de catálogo


def sku_grants_access(sku: str, sector_key: str, tier: str) -> bool:
    """¿El SKU concede acceso a (sector_key, tier)? Verdadero si algún grant cubre el scope
    (sector o '*') con un nivel ≥ el pedido."""
    want = _LEVEL_RANK.get(tier, 99)
    for scope, level in sku_grants(sku):
        if scope in ("*", sector_key) and _LEVEL_RANK.get(level, -1) >= want:
            return True
    return False


def sku_label(sku: str) -> str:
    """Etiqueta legible (español) de un SKU. Best-effort."""
    try:
        kind, ref = parse_sku(sku)
    except SkuError:
        return sku
    if kind == "all_access":
        return "All-Access (todos los Insight)"
    if kind == "enterprise":
        return "Enterprise (todo el catálogo)"
    if kind == "special":
        return f"informe especial «{ref}»"
    entry = CATALOG_BY_KEY.get(ref)
    name = entry.display_name if entry else ref
    return f"Insight · {name}" if kind == "insight" else f"Deep Dive · {name}"


def entitlement_for_sku(sku: str) -> Optional[Tuple[str, ProductTier]]:
    """Si el SKU es una compra por-producto (Deep Dive), devuelve ``(sector, deep_dive)`` que
    el webhook otorgará vía ``grant_entitlement``. Suscripciones/special → None."""
    kind, ref = validate_sku(sku)
    if kind == "deep_dive" and ref is not None:
        return (ref, ProductTier.deep_dive)
    return None


def catalog_skus() -> list:
    """SKUs vendibles canónicos para poblar el tarifario en la UI de administración: por cada
    producto del catálogo, su ``insight:{sector}`` (suscripción) y su ``deep_dive:{sector}``
    (compra puntual), más los bundles ``all_access`` y ``enterprise``. ``special`` no se
    enumera (a medida). Cada item: ``{sku, kind, ref, label, intervals}``."""
    out = []
    for entry in PRODUCT_CATALOG:
        for mk, kind in ((insight_sku, "insight"), (deep_dive_sku, "deep_dive")):
            sku = mk(entry.sector_key)
            out.append({"sku": sku, "kind": kind, "ref": entry.sector_key,
                        "label": sku_label(sku), "intervals": allowed_intervals(sku)})
    for sku in (SKU_ALL_ACCESS, SKU_ENTERPRISE):
        out.append({"sku": sku, "kind": sku, "ref": None,
                    "label": sku_label(sku), "intervals": allowed_intervals(sku)})
    return out
