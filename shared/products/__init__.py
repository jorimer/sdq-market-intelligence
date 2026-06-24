"""Framework de productización sector-agnóstico (Pulse / Insight / Deep Dive).

Vive en ``shared/`` como transversal (igual que el Cerebro de Insights). Cada
sector implementa el ``Protocol`` ``SectorProduct`` + su ``SectorProductManifest``
y se cablea sin tocar este framework. Ver ``docs/SPEC_PLATFORM_PRODUCTIZATION.md``.
"""
from shared.products.access import (
    AccessDecision,
    AccessOutcome,
    TIER_FOR_LEVEL,
    can_access,
    enforce_access,
    required_tier_for,
    require_product_access,
)
from shared.products.anonymization import AnonymizationError, enforce_anonymized
from shared.products.assembler import assemble_product_report
from shared.products.contract import (
    DataHealth,
    ProductSnapshot,
    SectorProduct,
    ValidationState,
    required_signal_methods,
)
from shared.products.manifest import SectorProductManifest
from shared.products.readiness import GATE_WEIGHTS, compute_readiness, empty_readiness
from shared.products.registry import (
    CATALOG_BY_KEY,
    PRODUCT_CATALOG,
    CatalogEntry,
    get_product,
    is_implemented,
    register_product,
    registered_sectors,
)
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec

__all__ = [
    "ProductTier",
    "Granularity",
    "TierLevelSpec",
    "SectorProductManifest",
    "SectorProduct",
    "DataHealth",
    "ValidationState",
    "ProductSnapshot",
    "required_signal_methods",
    "assemble_product_report",
    "enforce_anonymized",
    "AnonymizationError",
    "compute_readiness",
    "empty_readiness",
    "GATE_WEIGHTS",
    "PRODUCT_CATALOG",
    "CATALOG_BY_KEY",
    "CatalogEntry",
    "register_product",
    "get_product",
    "is_implemented",
    "registered_sectors",
    "AccessDecision",
    "AccessOutcome",
    "TIER_FOR_LEVEL",
    "can_access",
    "enforce_access",
    "required_tier_for",
    "require_product_access",
]
