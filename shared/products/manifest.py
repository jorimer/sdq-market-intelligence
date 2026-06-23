"""Manifiesto de producto por sector — config-as-code.

Un ``SectorProductManifest`` declara las 3 definiciones de nivel de un sector. Es
la única fuente de verdad de qué lleva cada producto; cambiar el contenido de un
nivel = editar el manifiesto del sector, sin tocar el motor de render ni el
framework.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from shared.products.tiers import ProductTier, TierLevelSpec


@dataclass(frozen=True)
class SectorProductManifest:
    """Catálogo declarativo de los niveles de un sector."""

    sector_key: str
    display_name: str
    levels: Dict[ProductTier, TierLevelSpec]

    def __post_init__(self) -> None:
        for tier, spec in self.levels.items():
            if spec.tier != tier:
                raise ValueError(
                    f"Manifiesto de '{self.sector_key}': la clave {tier.value} no "
                    f"coincide con TierLevelSpec.tier={spec.tier.value}."
                )

    def require_level(self, tier: ProductTier) -> TierLevelSpec:
        """Devuelve la spec del nivel o lanza error en español si el sector no lo ofrece."""
        spec = self.levels.get(tier)
        if spec is None:
            raise ValueError(
                f"El sector '{self.sector_key}' no ofrece el nivel '{tier.value}'."
            )
        return spec

    def tiers(self) -> List[ProductTier]:
        """Niveles declarados, en orden canónico Pulse → Insight → Deep Dive."""
        order = {ProductTier.pulse: 0, ProductTier.insight: 1, ProductTier.deep_dive: 2}
        return sorted(self.levels.keys(), key=lambda t: order[t])
