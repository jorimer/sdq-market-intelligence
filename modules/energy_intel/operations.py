"""Energy-intel console operations — SIE + ONE power-sector resilience sync, and the OC-SENI feed."""
import logging
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger("sdq.energy.operations")


def _run_sie_energy_sync(params, user_id, set_phase) -> Dict:
    """Fetch SIE (capacity + claims) and ONE (generation mix) open data, persist IRSE.

    Backfill por año (cobertura plena 3/3): un score por cada año comparable, no solo
    el más reciente — así el selector de períodos del producto ofrece la serie real."""
    from modules.energy_intel.service import backfill_scores, sincronizar_imte

    set_phase("descargando capacidad, reclamaciones (SIE) y generación por tecnología (ONE)")
    db = SessionLocal()
    try:
        set_phase("calculando IRSE por año (backfill de cobertura plena)")
        # EL ÍNDICE Y EL FEED SON INDEPENDIENTES. El 2026-09-14 la SIE retiró el CSV de capacidad
        # y el backfill del IRSE lanzaba antes de llegar al IMTE: una fuente anual caída dejaba
        # sin sincronizar la mensual, que no depende de ella. Cada uno falla solo.
        try:
            resultado: Dict = dict(backfill_scores(db))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning("IRSE no recalculado: %s", e, exc_info=True)
            resultado = {"irse": {"error": f"{type(e).__name__}: {e}"}}
        # EL FEED MENSUAL NO TUMBA EL ÍNDICE: el IRSE ya quedó escrito y es anual. Si el OC no
        # responde, se registra en el resultado de la corrida y el sensor de fuentes lo verá
        # atrasar; no se reintenta a ciegas ni se pierde el índice.
        set_phase("descargando el Informe Mensual de Transacciones Económicas (OC-SENI)")
        try:
            resultado = {**resultado, "imte": sincronizar_imte(db)}
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning("IMTE del OC-SENI no sincronizado: %s", e, exc_info=True)
            resultado = {**resultado, "imte": {"error": f"{type(e).__name__}: {e}"}}
        if "error" in (resultado.get("irse") or {}) and "error" in (resultado.get("imte") or {}):
            # Las dos fuentes cayeron: la corrida SÍ falló, y así tiene que verse en la consola.
            raise RuntimeError(f"energía sin sincronizar: IRSE {resultado['irse']['error']} · "
                               f"IMTE {resultado['imte']['error']}")
        return resultado
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "sie-energy-sync", "Sincronizar energía (SIE + ONE)",
        "Descarga datos abiertos de la SIE (capacidad instalada del SENI y reclamaciones) "
        "y de la ONE (generación por tecnología → penetración renovable) desde "
        "datos.gob.do, y persiste el Índice de Resiliencia del Sector Eléctrico (IRSE) "
        "del último año con sus 3 dimensiones. Además baja el Informe Mensual de "
        "Transacciones Económicas del OC-SENI para el movimiento mensual. Dato público real.",
        # Mensual: el IMTE sale entre el 20 y el 22 de cada mes. El IRSE es anual y rehacerlo
        # cada mes es idempotente. ⚠️ En prod manda la agenda GUARDADA: cambiar este número no
        # alcanza, hay que hacer PUT /api/v1/operations/sie-energy-sync/schedule.
        _run_sie_energy_sync, default_interval_hours=720,
    ))


register()
