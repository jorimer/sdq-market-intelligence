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


def _assert_system_payload(product: SectorProduct, tier: ProductTier,
                           snapshot: ProductSnapshot):
    """Doctrina: un nivel de sistema (Pulse) jamás emite identificadores. Verifica el
    snapshot ANTES de narrar y devuelve el ``level`` (para reusar la granularidad)."""
    level = product.product_manifest().require_level(tier)
    if level.granularity == Granularity.system:
        if snapshot.entity_name is not None:
            raise AnonymizationError(
                f"Un nivel de sistema de '{product.sector_key}' no debe nombrar "
                f"entidad (entity_name='{snapshot.entity_name}')."
            )
        enforce_anonymized(snapshot.payload, entity_roster=snapshot.entity_roster)
    return level


def _assert_system_narratives(level, snapshot: ProductSnapshot, narratives) -> None:
    """Defensa en profundidad: el TEXTO de un Pulse tampoco puede nombrar entidad."""
    if level.granularity == Granularity.system:
        enforce_anonymized(narratives, entity_roster=snapshot.entity_roster)


async def _content_from_snapshot(
    product: SectorProduct,
    tier: ProductTier,
    snapshot: ProductSnapshot,
    lang: str,
) -> ProductContent:
    """Núcleo compartido: a partir de un snapshot (real o de muestra), aplica el sensor
    de anonimización Pulse y produce las narrativas vía el motor. NO renderiza."""
    level = _assert_system_payload(product, tier, snapshot)
    narratives = await product.narratives(tier, snapshot, lang)
    _assert_system_narratives(level, snapshot, narratives)
    return ProductContent(level=level, snapshot=snapshot, narratives=narratives)


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
    snapshot = product.snapshot(tier, period, scope)
    return await _content_from_snapshot(product, tier, snapshot, lang)


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


def supports_sample(product: SectorProduct) -> bool:
    """¿El producto ofrece una MUESTRA curada tier-1? La muestra es la pieza de conversión:
    exige el exemplar CURADO (``sample_narratives``) + los datos demo (``sample_snapshot``).
    NO basta con datos demo: no se sirve generación al vuelo como muestra. Un sector sin
    exemplar aún no ofrece muestra (botón apagado, honesto)."""
    return (callable(getattr(product, "sample_narratives", None))
            and callable(getattr(product, "sample_snapshot", None)))


async def assemble_sample_report(
    product: SectorProduct,
    tier: ProductTier,
    *,
    lang: str = "es",
    output_dir: Optional[str] = None,
) -> str:
    """Ensambla la MUESTRA (sector, nivel): datos demo sintéticos (``sample_snapshot``) +
    narrativa CURADA tier-1 (``sample_narratives``, exemplar — NO el motor IA), con la
    estampa ``sample=True`` ("MUESTRA — DATA ILUSTRATIVA"). No toca la DB ni datos reales.
    La calidad de la muestra no depende del motor en runtime. Corre el sensor de
    anonimización. Lanza ``ValueError`` (español) si el producto no ofrece exemplar."""
    snap_fn = getattr(product, "sample_snapshot", None)
    curated_fn = getattr(product, "sample_narratives", None)
    if not callable(snap_fn) or not callable(curated_fn):
        raise ValueError(f"'{product.sector_key}' no ofrece muestra curada todavía.")
    snapshot = snap_fn(tier)
    level = _assert_system_payload(product, tier, snapshot)
    narratives = curated_fn(tier)
    _assert_system_narratives(level, snapshot, narratives)
    return await product.render(
        tier, snapshot, narratives, sample=True, lang=lang, output_dir=output_dir,
    )
