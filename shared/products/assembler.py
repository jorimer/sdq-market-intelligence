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

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from shared.products.anonymization import AnonymizationError, enforce_anonymized
from shared.products.contract import ProductSnapshot, SectorProduct
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec

logger = logging.getLogger("sdq.products.assembler")

# Bumpear para invalidar TODA la caché de narrativas cuando cambie la lógica de generación
# (plantillas, prompt, guard). El fingerprint del payload cubre los cambios de DATO; esta
# versión cubre los cambios de CÓDIGO.
# "2": doctrina 2026-07-17 (TRADUCE EL TECNICISMO + registro llano de PROCEDENCIA/
# INCERTIDUMBRE) — sin el bump, los reportes cacheados seguirían sirviendo la voz vieja.
NARRATIVE_CACHE_VERSION = "2"


def _narrative_fingerprint(payload: Optional[Dict], tier: str, lang: str) -> str:
    """Hash del snapshot (dato) + tier + idioma + versión → clave de frescura de la caché.
    Si el dato subyacente cambia, el fingerprint cambia → MISS → se regenera."""
    raw = json.dumps(payload or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(
        f"{raw}|{tier}|{lang}|{NARRATIVE_CACHE_VERSION}".encode("utf-8")).hexdigest()


async def _narratives_cached(
    product: SectorProduct, tier: ProductTier, snapshot: ProductSnapshot,
    lang: str, scope: Optional[str],
) -> Dict[str, str]:
    """Narrativas del producto con caché por (sector, nivel, ámbito, período, idioma).

    HIT (fingerprint igual) → texto guardado al instante (evita ~15-90s de motor IA).
    MISS → genera y guarda en sitio. La caché NUNCA rompe la entrega: cualquier fallo de
    lectura/escritura cae a la generación directa."""
    from shared.products.models import ProductReportCache

    # Los productos guardan la sesión en `_db` (el contrato SectorProduct no expone `db`
    # público); aceptamos ambos por robustez. OJO: leer solo `db` dejaba esta caché MUERTA
    # —todo producto caía a "sin caché" y regeneraba en cada descarga (~15-90s)—. Sin sesión
    # (muestras/tests) → sin caché, correcto.
    db = getattr(product, "db", None) or getattr(product, "_db", None)
    if db is None:
        return await product.narratives(tier, snapshot, lang)

    fp = _narrative_fingerprint(snapshot.payload, tier.value, lang)
    key = dict(sector_key=product.sector_key, tier=tier.value,
               scope=scope or "", period=snapshot.period or "", lang=lang)
    row = None
    try:
        row = db.query(ProductReportCache).filter_by(**key).first()
        if row is not None and row.fingerprint == fp:
            return dict(row.narratives or {})  # HIT
    except Exception as e:  # noqa: BLE001 — la caché jamás debe tumbar la entrega
        logger.warning("caché de narrativas (lectura) no disponible: %s", e)
        return await product.narratives(tier, snapshot, lang)

    narratives = await product.narratives(tier, snapshot, lang)  # MISS → generar
    try:
        if row is None:
            row = ProductReportCache(**key)
            db.add(row)
        row.fingerprint = fp
        row.narratives = narratives
        db.commit()
    except Exception as e:  # noqa: BLE001 — una carrera/constraint no debe romper la entrega
        db.rollback()
        logger.warning("caché de narrativas (escritura) omitida: %s", e)
    return narratives


@dataclass(frozen=True)
class ProductContent:
    """Contenido estructurado de un (sector, nivel), ya con el sensor de anonimización
    aplicado. Lo comparten la vista in-app (JSON) y la descarga PDF: ambas parten del
    MISMO snapshot + narrativas, sin re-implementar la doctrina de cada superficie.

    ``section_order`` es el orden canónico de secciones a renderizar: las del nivel del
    producto + las secciones ESTÁNDAR auto-generadas (metodología/fuentes) anexadas al
    final (ver docs/REPORT_STANDARD.md). Las superficies iteran este orden."""

    level: TierLevelSpec
    snapshot: ProductSnapshot
    narratives: Dict[str, str]
    section_order: tuple = ()


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
    scope: Optional[str] = None,
) -> ProductContent:
    """Núcleo compartido: a partir de un snapshot (real o de muestra), aplica el sensor
    de anonimización Pulse y produce las narrativas vía el motor (con caché). NO renderiza."""
    level = _assert_system_payload(product, tier, snapshot)
    narratives = await _narratives_cached(product, tier, snapshot, lang, scope)
    # Secciones ESTÁNDAR auto-generadas (metodología/fuentes) — nuestra ventaja honesta.
    # Se anexan tras las del producto; las heredan online y PDF (docs/REPORT_STANDARD.md).
    from shared.products.report_sections import standard_sections
    std = standard_sections(product, tier)
    if std:
        narratives = {**narratives, **std}
    _assert_system_narratives(level, snapshot, narratives)
    order = tuple(level.sections) + tuple(k for k in std if k not in level.sections)
    return ProductContent(level=level, snapshot=snapshot, narratives=narratives,
                          section_order=order)


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
    return await _content_from_snapshot(product, tier, snapshot, lang, scope=scope)


async def assemble_product_report(
    product: SectorProduct,
    tier: ProductTier,
    *,
    period: str,
    scope: Optional[str] = None,
    sample: bool = False,
    lang: str = "es",
    output_dir: Optional[str] = None,
    fmt: str = "pdf",
) -> str:
    """Ensambla el reporte (sector, nivel) y devuelve el path (PDF o Word según ``fmt``).

    Sector-agnóstico: cualquier ``SectorProduct`` produce su reporte sin que el
    framework conozca su implementación. Reusa ``assemble_product_content`` (mismo
    snapshot + narrativas + sensor de anonimización que la vista in-app) y solo añade
    el render. ``fmt`` = "pdf" | "docx" — misma anatomía de marca.
    """
    content = await assemble_product_content(
        product, tier, period=period, scope=scope, lang=lang)
    return await product.render(
        tier, content.snapshot, content.narratives,
        sample=sample, lang=lang, output_dir=output_dir, fmt=fmt,
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
