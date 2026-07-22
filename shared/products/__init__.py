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
from shared.products.assembler import (
    ProductContent,
    assemble_product_content,
    assemble_product_report,
    assemble_sample_report,
    supports_sample,
)
from shared.products.contract import (
    CanonicalForecast,
    CanonicalScore,
    CanonicalSeries,
    DataHealth,
    ForecastObservation,
    ProductSnapshot,
    ScoreObservation,
    SectorProduct,
    SeriesObservation,
    SignalItem,
    ValidationState,
    required_signal_methods,
)
from shared.products.manifest import SectorProductManifest
from shared.products.narrative_depth import (
    SHORT_CLOSE_SECTIONS,
    STATIC_SECTIONS,
    section_mode,
)
from shared.products.periods import distinct_periods, period_sort_key
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
    "CanonicalSeries",
    "SeriesObservation",
    "CanonicalScore",
    "ScoreObservation",
    "SignalItem",
    "CanonicalForecast",
    "ForecastObservation",
    "required_signal_methods",
    "assemble_product_report",
    "assemble_product_content",
    "assemble_sample_report",
    "supports_sample",
    "ProductContent",
    "enforce_anonymized",
    "AnonymizationError",
    "compute_readiness",
    "empty_readiness",
    "GATE_WEIGHTS",
    "distinct_periods",
    "period_sort_key",
    "section_mode",
    "SHORT_CLOSE_SECTIONS",
    "STATIC_SECTIONS",
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
