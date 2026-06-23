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

from typing import Optional

from shared.products.anonymization import AnonymizationError, enforce_anonymized
from shared.products.contract import SectorProduct
from shared.products.tiers import Granularity, ProductTier


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
    framework conozca su implementación. Lanza ``ValueError`` (español) si el sector
    no ofrece el nivel, y ``AnonymizationError`` si un Pulse filtra identificadores.
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
    # entidad (aunque el guard del motor ya lo limita, lo verificamos antes de render).
    if is_system:
        enforce_anonymized(narratives, entity_roster=snapshot.entity_roster)

    return await product.render(
        tier, snapshot, narratives,
        sample=sample, lang=lang, output_dir=output_dir,
    )
