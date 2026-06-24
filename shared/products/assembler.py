"""Ensamblador genérico de reportes de producto.

Orquesta la producción de un reporte (sector, nivel) usando SOLO el contrato
``SectorProduct`` — nunca importa un módulo de sector. El flujo es uniforme:

    manifiesto → snapshot del nivel → (sensor de anonimización si es Pulse) →
    narrativas (motor compartido vía el sector) → render (vía el sector)

El "motor" pesado (Claude/narrativa) ya es compartido (``shared/narrative``); este
ensamblador es el director de orquesta. Las cifras se generan dentro del sector con
``cifras_derivadas`` + ``numeric_guard`` (anti-alucinación), no aquí.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from shared.products.anonymization import AnonymizationError, enforce_anonymized
from shared.products.contract import ProductSnapshot, SectorProduct
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec


@dataclass(frozen=True)
class ProductContent:
    """Contenido estructurado de un (sector, nivel), ya con el sensor de anonimización
    aplicado. Lo comparten la vista in-app (JSON) y la descarga PDF: ambas parten del
    MISMO snapshot + narrativas, sin re-implementar la doctrina de cada superficie."""

    level: TierLevelSpec
    snapshot: ProductSnapshot
    narratives: Dict[str, str]


async def assemble_product_content(
    product: SectorProduct,
    tier: ProductTier,
    *,
    period: str,
    scope: Optional[str] = None,
    lang: str = "es",
) -> ProductContent:
    """Produce el contenido (snapshot + narrativas) de un (sector, nivel) aplicando el
    sensor de anonimización Pulse. NO renderiza — es el núcleo compartido entre la vista
    in-app y el PDF. Lanza ``ValueError`` (español) si el sector no ofrece el nivel o el
    snapshot no es resoluble, y ``AnonymizationError`` si un Pulse filtra identificadores.
    """
    manifest = product.product_manifest()
    level = manifest.require_level(tier)  # error en español si no existe

    snapshot = product.snapshot(tier, period, scope)

    # Doctrina: un nivel de sistema (Pulse) jamás emite identificadores de entidad.
    is_system = level.granularity == Granularity.system
    if is_system:
        if snapshot.entity_name is not None:
            raise AnonymizationError(
                f"Un nivel de sistema de '{product.sector_key}' no debe nombrar "
                f"entidad (entity_name='{snapshot.entity_name}')."
            )
        enforce_anonymized(snapshot.payload, entity_roster=snapshot.entity_roster)

    narratives = await product.narratives(tier, snapshot, lang)

    # Defensa en profundidad: el TEXTO narrado de un Pulse tampoco puede nombrar
    # entidad (aunque el guard del motor ya lo limita, lo verificamos antes de servir).
    if is_system:
        enforce_anonymized(narratives, entity_roster=snapshot.entity_roster)

    return ProductContent(level=level, snapshot=snapshot, narratives=narratives)


async def assemble_product_report(
    product: SectorProduct,
    tier: ProductTier,
    *,
    period: str,
    scope: Optional[str] = None,
    sample: bool = False,
    lang: str = "es",
    output_dir: Optional[str] = None,
) -> str:
    """Ensambla el reporte (sector, nivel) y devuelve el path del PDF.

    Sector-agnóstico: cualquier ``SectorProduct`` produce su reporte sin que el
    framework conozca su implementación. Reusa ``assemble_product_content`` (mismo
    snapshot + narrativas + sensor de anonimización que la vista in-app) y solo añade
    el render a PDF.
    """
    content = await assemble_product_content(
        product, tier, period=period, scope=scope, lang=lang)
    return await product.render(
        tier, content.snapshot, content.narratives,
        sample=sample, lang=lang, output_dir=output_dir,
    )
