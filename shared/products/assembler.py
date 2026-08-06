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

# Bump MANUAL para cambios de lógica que no viven en los prompts (p. ej. el ensamblado de
# secciones acá). Los cambios de PROMPT/modelo/guardrail ya NO dependen de esta constante:
# los cubre `_narrative_logic_version()`.
# "2": doctrina 2026-07-17 (TRADUCE EL TECNICISMO + registro llano de PROCEDENCIA/
# INCERTIDUMBRE) — sin el bump, los reportes cacheados seguirían sirviendo la voz vieja.
NARRATIVE_CACHE_VERSION = "2"


def _narrative_logic_version() -> str:
    """Huella de la RECETA de narrativa (prompts compartidos + doctrina + modelo + guard).

    Por qué derivada y no una constante a mano: esta caché vive en Postgres y —a diferencia
    de la L2 de Redis— **no tiene TTL**; se invalida solo si cambia el dato. En un sector con
    el dato quieto, una narrativa cacheada vive indefinidamente. El bump manual estaba
    documentado ("sin el bump… seguirían sirviendo la voz vieja") y aun así no se movió desde
    que se creó: entre medio se desplegaron `NO_META_COMMENTARY` (#580), el veto de léxico
    visceral y `DIRECTION_DISCIPLINE` (#631), o sea tres arreglos de cara al cliente que
    pudieron quedar sin efecto acá. Un mecanismo correcto que depende de que alguien recuerde
    es un mecanismo roto; se deriva del contenido real de los prompts.
    """
    from shared.config.settings import settings
    from shared.narrative import cerebro
    from shared.narrative.numeric_guard import GUARD_VERSION

    parts = [
        GUARD_VERSION,
        settings.ANTHROPIC_MODEL or "",
        cerebro.REGISTER_NEUTRO,
        cerebro.EPISTEMIC_STANDARD,
        cerebro.NO_META_COMMENTARY,
        cerebro.DIRECTION_DISCIPLINE,
        cerebro.BARRA_DE_INSIGHT,
        cerebro.CEREBRO_IDENTITY,
    ]
    parts += [v for _, v in sorted(cerebro.AXIS_DOCTRINE.items())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _narrative_fingerprint(payload: Optional[Dict], tier: str, lang: str) -> str:
    """Hash del snapshot (dato) + tier + idioma + versión + RECETA → clave de frescura.
    Si cambia el dato subyacente O la forma de generar el texto, el fingerprint cambia →
    MISS → se regenera. Sin la receta, un arreglo de prompt no se veía nunca acá."""
    raw = json.dumps(payload or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(
        f"{raw}|{tier}|{lang}|{NARRATIVE_CACHE_VERSION}|"
        f"{_narrative_logic_version()}".encode("utf-8")).hexdigest()


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
    from shared.narrative.claude_engine import is_static_fallback_text
    row = None
    try:
        row = db.query(ProductReportCache).filter_by(**key).first()
        if row is not None and row.fingerprint == fp:
            cached = dict(row.narratives or {})
            # DEFENSA / AUTO-SANADO: una fila escrita ANTES de que existiera el guard
            # anti-envenenamiento (o por cualquier regresión futura) puede contener fallback
            # estático. Vive en Postgres → sobrevive deploys y se sirve en un HIT SILENCIOSO
            # sin tocar el motor: un Deep Dive premium queda hueco de forma permanente y
            # determinista (el síntoma exacto de las filas cacheadas el 2026-07-27 durante una
            # degradación transitoria, antes del guard de escritura). Si el HIT está degradado
            # se trata como MISS: se regenera y —si el motor ya responde— se re-cachea sano,
            # sin cirugía manual de BD. El log de HIT (antes ausente) da observabilidad.
            if cached and any(is_static_fallback_text(v) for v in cached.values()):
                logger.warning(
                    "caché de narrativas HIT DEGRADADA en %s/%s (scope=%s, período=%s): "
                    "fila envenenada (fallback estático cacheado) — se ignora y regenera.",
                    product.sector_key, tier.value, scope or "", snapshot.period or "")
            else:
                logger.info(
                    "caché de narrativas HIT en %s/%s (scope=%s, período=%s).",
                    product.sector_key, tier.value, scope or "", snapshot.period or "")
                return cached  # HIT sano
    except Exception as e:  # noqa: BLE001 — la caché jamás debe tumbar la entrega
        logger.warning("caché de narrativas (lectura) no disponible: %s", e)
        return await product.narratives(tier, snapshot, lang)

    narratives = await product.narratives(tier, snapshot, lang)  # MISS → generar
    # NUNCA persistir texto degradado: si el motor IA cayó al fallback estático (rate-limit,
    # outage o corte de presupuesto), cachearlo serviría el mismo relleno hueco incluso
    # después de que el servicio se recupere (envenenamiento de caché). Se devuelve tal cual
    # para que el gate premium de `_content_from_snapshot` decida; la próxima descarga
    # regenerará de verdad. (``is_static_fallback_text`` ya importado arriba.)
    if any(is_static_fallback_text(v) for v in narratives.values()):
        logger.warning(
            "Narrativa degradada a fallback estático en %s/%s (scope=%s, período=%s): "
            "no se cachea; la próxima descarga reintenta.",
            product.sector_key, tier.value, scope or "", snapshot.period or "")
        return narratives
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
    # GATE DE DEGRADACIÓN: si el motor IA cayó al fallback estático en secciones de ANÁLISIS
    # del nivel, un Deep Dive/Insight —que ES el producto pago completo— saldría hueco
    # ("El análisis ampliado se incorpora en la versión completa del producto"), engañoso y
    # dañino para la marca. Se detecta sobre el TEXTO ya ensamblado (los productos descartan
    # model_used) y se decide por tier: los premium (nombrados) FALLAN cerrado con un error de
    # reintento; el Pulse (abierto) solo se registra. Umbral = 1: una sola sección de análisis
    # degradada ya invalida un premium. La caché nunca guardó este texto (ver _narratives_cached),
    # así que al recuperarse el servicio la próxima descarga regenera de verdad.
    from shared.narrative.claude_engine import NarrativeDegradedError, degraded_sections
    degraded = degraded_sections(narratives, level.sections)
    if degraded:
        blocked = level.granularity is not Granularity.system
        logger.warning(
            "Reporte %s/%s (scope=%s, período=%s) con %d/%d sección(es) de análisis "
            "degradada(s) a fallback estático: %s",
            product.sector_key, tier.value, scope or "", snapshot.period or "",
            len(degraded), len(level.sections), degraded)
        # Telemetría de ops (evento interno, no público). Best-effort: no rompe la entrega.
        from shared.narrative.degradation_events import emit_narrative_degraded
        emit_narrative_degraded(
            surface="products", sector_key=product.sector_key, tier=tier.value,
            sections=degraded, blocked=blocked, scope=scope, period=snapshot.period)
        if blocked:
            raise NarrativeDegradedError(degraded)
    # Glosario automático (audiencia mixta): detecta las siglas/términos técnicos que la
    # narrativa YA REDACTADA usa y anexa su definición. Va ANTES del merge de las secciones
    # estándar (metodología/fuentes no llevan jerga propia del eje). Punto único: lo
    # heredan la vista in-app (JSON) y el PDF/Word para todos los módulos de sector.
    from shared.products.report_sections import glossary_section, standard_sections
    # Solo valores str: una fila de caché con un valor no-str (columna JSON) no debe
    # tumbar la entrega — misma doctrina defensiva que las secciones estándar.
    glossary = glossary_section(
        "\n\n".join(v for v in narratives.values() if isinstance(v, str)), tier)
    if glossary:
        narratives = {**narratives, **glossary}
    # Secciones ESTÁNDAR auto-generadas (metodología/fuentes) — nuestra ventaja honesta.
    # Se anexan tras las del producto; las heredan online y PDF (docs/REPORT_STANDARD.md).
    # El corte del snapshot ancla la metodología: sin él la sección habla del estado ACTUAL
    # de la plataforma (cobertura, frescura) dentro de un informe fechado antes.
    std = standard_sections(product, tier, as_of=snapshot.period or None)
    if std:
        narratives = {**narratives, **std}
    _assert_system_narratives(level, snapshot, narratives)
    extra = {**glossary, **std}
    order = tuple(level.sections) + tuple(k for k in extra if k not in level.sections)
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
    out: Optional[dict] = None,
) -> str:
    """Ensambla el reporte (sector, nivel) y devuelve el path (PDF o Word según ``fmt``).

    Sector-agnóstico: cualquier ``SectorProduct`` produce su reporte sin que el
    framework conozca su implementación. Reusa ``assemble_product_content`` (mismo
    snapshot + narrativas + sensor de anonimización que la vista in-app) y solo añade
    el render. ``fmt`` = "pdf" | "docx" — misma anatomía de marca.

    ``out`` (opcional): si se pasa un dict, se rellena con metadatos del reporte —hoy
    ``out["period"]`` = el período REAL de los datos ensamblados (``snapshot.period``),
    que puede diferir del ``period`` PEDIDO (p.ej. el Deep Dive resuelve al último dato
    disponible: se pide "2025" y el corte real es "2026-05"). El caller lo usa para
    nombrar la descarga en coherencia con la portada; sin ``out`` el comportamiento no
    cambia (los tests no lo pasan).
    """
    content = await assemble_product_content(
        product, tier, period=period, scope=scope, lang=lang)
    if out is not None:
        out["period"] = content.snapshot.period
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
