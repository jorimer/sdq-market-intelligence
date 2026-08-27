"""Manifiesto de producto por sector — config-as-code.

Un ``SectorProductManifest`` declara las 3 definiciones de nivel de un sector. Es
la única fuente de verdad de qué lleva cada producto; cambiar el contenido de un
nivel = editar el manifiesto del sector, sin tocar el motor de render ni el
framework.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from shared.products.tiers import ProductTier, TierLevelSpec


@dataclass(frozen=True)
class SectorProductManifest:
    """Catálogo declarativo de los niveles de un sector."""

    sector_key: str
    display_name: str
    levels: Dict[ProductTier, TierLevelSpec]

    #: Clave del producto HERMANO cuya unidad de observación es el AÑO, cuando existe.
    #:
    #: Sirve para que el selector de períodos de este producto ofrezca **las dos** lecturas
    #: —el corte y el año— sin que la pantalla tenga que conocer la pareja. Se declara acá y
    #: no en el frontend porque un producto anual nuevo (seguros, pensiones) tiene que
    #: aparecer solo: cablear la pareja en la pantalla es cómo al anuario le faltaron cuatro
    #: registros de a uno y ninguno falló.
    #:
    #: NO es una jerarquía ni una sección: son dos productos con su propio acceso, su propio
    #: precio y su propio tipo de informe. Lo único que declara esta clave es «el año de este
    #: sujeto se pide allá».
    #:
    #: Lo vigila `shared/products/tests/test_producto_anual_declarado.py`: la clave declarada
    #: tiene que existir en el catálogo y servir períodos con forma de AÑO.
    annual_companion: Optional[str] = None

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
