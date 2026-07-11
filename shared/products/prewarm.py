"""Pre-calentado de la caché de narrativas de productos (cache warming).

Genera por adelantado las narrativas IA de los productos PUBLICADOS y las persiste en
``product_report_cache``, de modo que hasta la 1ª descarga del usuario sea instantánea
(la generación IA ya ocurrió, no en el momento de la descarga).

IDEMPOTENTE: reusa ``assemble_product_content`` → ``_narratives_cached``, así que un
(sector, nivel, ámbito, período, idioma) con el mismo fingerprint es un HIT y NO regenera —
solo se paga IA cuando el dato subyacente cambió. Por eso correrlo periódicamente es barato:
la primera pasada genera todo; las siguientes solo tocan lo que cambió.

ACOTADO a:
- Productos PUBLICADOS (``ProductActivation.is_active``): no se calienta lo no vendible.
- Niveles caros/vendibles (insight, deep_dive). El Pulse es abierto y de una sola sección
  (barato al vuelo); no vale la pena precalentarlo.
- Idiomas configurables; por defecto solo ``es`` (agregar en/fr cuando se quiera pagar su
  generación — cada idioma es una fila y una generación aparte).

NO corre inline al persistir un snapshot (eso bloquearía el sync minutos y dispararía
decenas de generaciones): es una operación de consola desacoplada, agendable.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from shared.products import Granularity, ProductTier
from shared.products.access import _is_activated
from shared.products.assembler import assemble_product_content
from shared.products.registry import get_product, registered_sectors

logger = logging.getLogger("sdq.products.prewarm")

# Niveles caros/vendibles que vale la pena precalentar (el Pulse es barato/abierto).
_WARM_TIERS: tuple = (ProductTier.insight, ProductTier.deep_dive)


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


async def prewarm_report_cache(
    db: Session,
    *,
    langs: Sequence[str] = ("es",),
    tiers: Sequence[ProductTier] = _WARM_TIERS,
    set_phase=None,
) -> Dict:
    """Precalienta la caché de narrativas de TODOS los productos publicados.

    Recorre cada (sector publicado, nivel en ``tiers``, ámbito, idioma) y ensambla el
    contenido, lo que genera+cachea las narrativas si el fingerprint cambió (HIT barato si
    no). Devuelve el conteo para el panel de Operaciones. Best-effort por combo: un fallo
    aislado (p. ej. una entidad sin datos, un snapshot no resoluble) se registra y no aborta
    el resto del warm.
    """
    set_phase = set_phase or (lambda _m: None)
    warmed = 0
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
                    label = f"{sector}/{tier.value} · {scope or '—'} · {lang}"
                    set_phase(f"precalentando {label}")
                    try:
                        await assemble_product_content(
                            product, tier, period="", scope=scope, lang=lang)
                        warmed += 1
                    except Exception as e:  # noqa: BLE001 — un combo no tumba el warm global
                        logger.warning("prewarm %s falló: %s", label, e)
                        errors.append(f"{label}: {e}")
    result = {
        "warmed": warmed,
        "skipped_unpublished": skipped_unpublished,
        "n_errors": len(errors),
        "errors": errors[:50],
        "langs": list(langs),
        "tiers": [t.value for t in tiers],
    }
    logger.info("prewarm-report-cache: %s",
                {k: v for k, v in result.items() if k != "errors"})
    return result
