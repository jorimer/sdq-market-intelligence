"""El sensor de anonimización sobre los Pulses YA guardados en caché. Sin llamar al modelo.

**El hueco.** Desde #1173 todo Pulse de un eje con entidades le pasa su roster al sensor. La
caché de narrativas (`ProductReportCache`, Postgres, sin TTL) guarda textos escritos ANTES,
cuando el sensor corría con el roster vacío. Un texto así que nombre a una entidad no se
detecta al guardarlo: se detecta la próxima vez que alguien lo pide, y el cliente recibe un 500.
Pedir cada período para averiguarlo tampoco sirve: un período que no está en caché se GENERA,
y eso cuesta.

**Lo que hace.** Lee las filas de nivel `pulse` de la caché, rearma el snapshot de ese período
—solo base de datos— para obtener el roster que el producto usa HOY, y corre
`enforce_anonymized` sobre el texto guardado. Recalcula además la huella: una fila con la huella
vigente es la que se sirve (un nombre ahí es un 500 real); una con huella vieja ya no se sirve y
se regenerará sola. Las dos se listan, marcadas.

**Lo que NO hace.** No borra ni reescribe filas: decidir qué hacer con una fila vetada es otra
decisión. Y no juzga cifras — eso exige el contexto de la sección, que la caché no guarda.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.observability.anonimizacion_en_cache")

#: Tope de filas leídas. Es una consulta de consola, no un export.
MAX_FILAS = 2000


def _nombre_vetado(narrativas: Dict[str, Any], roster) -> Optional[str]:
    """El mensaje del sensor si el texto nombra a alguien del roster; None si pasa."""
    from shared.products.anonymization import AnonymizationError, enforce_anonymized

    try:
        enforce_anonymized(narrativas, entity_roster=roster)
    except AnonymizationError as e:
        return str(e)
    return None


def escanear_pulses_cacheados(db: Session, sector: Optional[str] = None,
                              limite: int = MAX_FILAS) -> Dict[str, Any]:
    """Corre el sensor de anonimización sobre cada Pulse cacheado con el roster vigente."""
    from shared.products import Granularity, ProductTier
    from shared.products.assembler import _narrative_fingerprint
    from shared.products.models import ProductReportCache
    from shared.products.registry import get_product

    q = db.query(ProductReportCache).filter(ProductReportCache.tier == ProductTier.pulse.value)
    if sector:
        q = q.filter(ProductReportCache.sector_key == sector)
    filas = q.limit(max(1, min(limite, MAX_FILAS))).all()

    por_sector: Dict[str, Dict[str, Any]] = {}
    for fila in filas:
        clave, periodo, idioma = str(fila.sector_key), str(fila.period or ""), str(fila.lang or "es")
        res = por_sector.setdefault(clave, {
            "filas": 0, "vigentes": 0, "sin_roster": 0, "sin_snapshot": 0, "vetadas": []})
        res["filas"] += 1
        producto = get_product(clave, db)
        if producto is None:
            res["sin_snapshot"] += 1
            continue
        nivel = producto.product_manifest().levels.get(ProductTier.pulse)
        if nivel is None or nivel.granularity != Granularity.system:
            continue
        try:
            with db.begin_nested():
                snap = producto.snapshot(ProductTier.pulse, periodo, None)
        except Exception as e:  # noqa: BLE001 — un período que ya no resuelve se declara
            res["sin_snapshot"] += 1
            logger.warning("snapshot del Pulse %s/%s no disponible para el escaneo: %s",
                           clave, periodo, e)
            continue
        vigente = str(fila.fingerprint) == _narrative_fingerprint(
            snap.payload, ProductTier.pulse.value, idioma,
            modulo_producto=type(producto).__module__)
        res["vigentes"] += int(vigente)
        if not snap.entity_roster:
            # Un eje declarado sin roster (país, sector) no tiene a quién anonimizar: se cuenta
            # para que el total cuadre, no se barre contra un roster vacío que siempre pasa.
            res["sin_roster"] += 1
            continue
        motivo = _nombre_vetado(fila.narratives if isinstance(fila.narratives, dict) else {},
                                snap.entity_roster)
        if motivo:
            res["vetadas"].append({"periodo": fila.period, "idioma": fila.lang,
                                   "vigente": vigente, "motivo": motivo})

    vetadas_vigentes: List[Dict[str, Any]] = [
        {"sector": s, **v} for s, r in por_sector.items() for v in r["vetadas"] if v["vigente"]]
    return {
        "sector": sector,
        "filas_leidas": len(filas),
        "truncado": len(filas) >= min(limite, MAX_FILAS),
        "por_sector": por_sector,
        "vetadas_vigentes": vetadas_vigentes,
        "como_leerlo": (
            "Cada fila vetada es un Pulse guardado cuyo TEXTO nombra a una entidad del roster "
            "vigente del eje. `vigente=true`: su huella es la actual, se sirve tal cual y quien "
            "lo pida recibe un 500. `vigente=false`: la huella cambió, ya no se sirve y se "
            "regenerará al pedirlo. `sin_roster` son ejes declarados sin entidades; "
            "`sin_snapshot`, períodos que ya no resuelven. No se generó nada ni se tocó la caché."),
    }
