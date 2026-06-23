"""Framework de productización sector-agnóstico (Pulse / Insight / Deep Dive).

Vive en ``shared/`` como transversal (igual que el Cerebro de Insights). Cada
sector implementa el ``Protocol`` ``SectorProduct`` + su ``SectorProductManifest``
y se cablea sin tocar este framework. Ver ``docs/SPEC_PLATFORM_PRODUCTIZATION.md``.
"""
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
]
