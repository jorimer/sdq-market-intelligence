"""Construction-intel console operations — MIVHED + BCRD + ONE construction sync."""
import logging
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger("sdq.construction_intel.operations")


def _run_construction_sync(params, user_id, set_phase) -> Dict:
    """MIVHED + BCRD + ONE: persiste el ICC anual Y el flujo MENSUAL de licencias.

    Una sola descarga del CSV para las dos lecturas. Pedirlo dos veces pagaría la red dos
    veces por el mismo fichero y, peor, admitiría que el mensual y el anual del mismo informe
    salieran de descargas distintas: si el emisor publica entre una y otra, dejan de cuadrar.

    El feed es BEST-EFFORT respecto del índice: si la lectura mensual falla, el ICC se
    persiste igual. El índice anual es el producto publicado y no puede caerse por una
    sección que todavía es piloto.
    """
    from modules.construction_intel.service import (
        backfill_scores, ingest_observaciones_mensuales)
    from shared.data.mivhed_client import mivhed_client

    set_phase("descargando MIVHED (licencias) + BCRD (PIB) + ONE (valor tasado por tipología)")
    ambas = mivhed_client.licenses_ambas()
    db = SessionLocal()
    try:
        set_phase("calculando ICC por año (coyuntura del sector construcción)")
        out = backfill_scores(db, licenses_by_year=ambas["anual"])
        set_phase("persistiendo el flujo mensual de licencias")
        try:
            out["feed_mensual"] = ingest_observaciones_mensuales(db, ambas["mensual"])
        except Exception as e:  # noqa: BLE001 — el feed no tumba el índice
            db.rollback()
            logger.warning("feed mensual del MIVHED no persistido: %s", e)
            out["feed_mensual"] = {"error": str(e)}
        return out
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "mivhed-construction-sync", "Sincronizar construcción (MIVHED + BCRD + ONE)",
        "Descarga las licencias de construcción del MIVHED (datos.gob.do), el crecimiento "
        "real del PIB de construcción del BCRD y el valor tasado por tipología de la ONE "
        "(one.gob.do), y persiste el Índice de Construcción (ICC) del último año completo "
        "MÁS el flujo mensual de licencias. Dato público real (permisos líder + producción "
        "efectiva + valor tasado autoritativo).",
        # 720 h y no 2160: el ICC sigue siendo anual, pero el feed de licencias es MENSUAL y
        # una cadencia anual lo dejaría hasta once meses sin mirar. Triplica las corridas de
        # sync — red y cómputo, no modelo.
        _run_construction_sync, default_interval_hours=720,
    ))


register()
