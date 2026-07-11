"""Pre-calentado de la caché de narrativas de productos (cache warming).

Genera por adelantado las narrativas IA de los productos PUBLICADOS y las persiste en
``product_report_cache``, de modo que hasta la 1ª descarga del usuario sea instantánea
(la generación IA ya ocurrió, no en el momento de la descarga).

IDEMPOTENTE: reusa ``assemble_product_content`` → ``_narratives_cached``, así que un
(sector, nivel, ámbito, período, idioma) con el mismo fingerprint es un HIT y NO regenera —
solo se paga IA cuando el dato subyacente cambió. Por eso correrlo periódicamente es barato:
la primera pasada genera todo; las siguientes solo tocan lo que cambió. La idempotencia
también lo hace RESUMIBLE: si un deploy corta la corrida a la mitad, la próxima retoma
saltando lo ya calentado (HITs).

ACOTADO a:
- Productos PUBLICADOS (``ProductActivation.is_active``): no se calienta lo no vendible.
- Niveles caros/vendibles (insight, deep_dive). El Pulse es abierto y de una sola sección.
- Idiomas configurables; por defecto solo ``es``.

CONCURRENCIA: los reportes se calientan en paralelo (bounded) para no dejar ociosos los cupos
del motor entre un reporte y el siguiente. El techo REAL de throughput es el semáforo de IA
del motor (``NarrativeEngine._MAX_CONCURRENCY``); esta cota solo evita el desperdicio de los
bordes. Cada reporte usa su PROPIA sesión (una Session de SQLAlchemy no es segura para uso
concurrente entre corrutinas).

NO corre inline al persistir un snapshot: es una operación de consola desacoplada, agendable,
y se dispara sola tras cada evento de datos (ver ``shared/products/events.py``).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.products import Granularity, ProductTier
from shared.products.access import _is_activated
from shared.products.assembler import assemble_product_content
from shared.products.registry import get_product, registered_sectors

logger = logging.getLogger("sdq.products.prewarm")

# Niveles caros/vendibles que vale la pena precalentar (el Pulse es barato/abierto).
_WARM_TIERS: tuple = (ProductTier.insight, ProductTier.deep_dive)

# Reportes calentados EN PARALELO. Conservador: el cuello real es el semáforo de IA del motor
# (5); esto solo llena los cupos ociosos entre reportes. Cada reporte concurrente toma una
# conexión de DB propia → se mantiene holgado bajo el pool (5 + overflow 10).
_REPORT_CONCURRENCY = 4


def _scopes_for(product, level) -> List[Optional[str]]:
    """Ámbitos a precalentar para (product, nivel).

    - ``system`` (agregado nacional) → un único ``None`` (sin entidad).
    - ``named_entity`` → todas las entidades elegibles del selector (``scope_options``),
      que ya filtra a las que producen reporte. Sin selector (o si falla) → ``[]``.
    """
    if level.granularity == Granularity.system:
        return [None]
    fn = getattr(product, "scope_options", None)
    if not callable(fn):
        return []
    try:
        return [o["value"] for o in (fn() or []) if o.get("value")]
    except Exception as e:  # noqa: BLE001 — un sector sin catálogo no debe romper el warm global
        logger.warning("scope_options de %s falló (se omite): %s", getattr(product, "sector_key", "?"), e)
        return []


def _enumerate_combos(
    db: Session, langs: Sequence[str], tiers: Sequence[ProductTier],
) -> Tuple[List[Tuple[str, ProductTier, Optional[str], str]], int, List[str]]:
    """(secuencial, sobre la sesión compartida) → los combos (sector publicado, nivel, ámbito,
    idioma) a calentar, el conteo de niveles NO publicados y los errores de enumeración."""
    combos: List[Tuple[str, ProductTier, Optional[str], str]] = []
    skipped_unpublished = 0
    errors: List[str] = []
    for sector in registered_sectors():
        product = get_product(sector, db)
        if product is None:
            continue
        try:
            manifest = product.product_manifest()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sector}: manifest — {e}")
            continue
        for tier in tiers:
            if tier not in manifest.levels:
                continue
            if not _is_activated(db, sector, tier):
                skipped_unpublished += 1
                continue
            level = manifest.require_level(tier)
            for scope in _scopes_for(product, level):
                for lang in langs:
                    combos.append((sector, tier, scope, lang))
    return combos, skipped_unpublished, errors


async def prewarm_report_cache(
    db: Session,
    *,
    langs: Sequence[str] = ("es",),
    tiers: Sequence[ProductTier] = _WARM_TIERS,
    concurrency: int = _REPORT_CONCURRENCY,
    set_phase=None,
) -> Dict:
    """Precalienta la caché de narrativas de TODOS los productos publicados.

    Enumera los combos (sector publicado, nivel, ámbito, idioma) y los ensambla en PARALELO
    acotado — cada uno genera+cachea las narrativas si el fingerprint cambió (HIT barato si
    no). Devuelve el conteo para el panel de Operaciones. Best-effort por combo: un fallo
    aislado (p. ej. una entidad sin datos) se registra y no aborta el resto del warm.
    """
    set_phase = set_phase or (lambda _m: None)
    combos, skipped_unpublished, errors = _enumerate_combos(db, langs, tiers)
    total = len(combos)
    sem = asyncio.Semaphore(max(1, concurrency))
    counter = {"done": 0}

    async def _warm(combo: Tuple[str, ProductTier, Optional[str], str]) -> Optional[str]:
        sector, tier, scope, lang = combo
        label = f"{sector}/{tier.value} · {scope or '—'} · {lang}"
        async with sem:
            # Sesión PROPIA por reporte: una Session no es segura para uso concurrente entre
            # corrutinas (los await del motor IA intercalarían sus operaciones de DB).
            wdb = SessionLocal()
            try:
                product = get_product(sector, wdb)
                await assemble_product_content(product, tier, period="", scope=scope, lang=lang)
                return None
            except Exception as e:  # noqa: BLE001 — un combo no tumba el warm global
                logger.warning("prewarm %s falló: %s", label, e)
                return f"{label}: {e}"
            finally:
                wdb.close()
                counter["done"] += 1
                set_phase(f"precalentado {counter['done']}/{total} · {label}")

    results = await asyncio.gather(*(_warm(c) for c in combos))
    errors += [r for r in results if r]
    warmed = sum(1 for r in results if r is None)
    result = {
        "warmed": warmed,
        "skipped_unpublished": skipped_unpublished,
        "n_errors": len(errors),
        "errors": errors[:50],
        "langs": list(langs),
        "tiers": [t.value for t in tiers],
        "concurrency": concurrency,
    }
    logger.info("prewarm-report-cache: %s",
                {k: v for k, v in result.items() if k != "errors"})
    return result
