"""Tourism-intel console operations — ONE arrivals traction sync."""
import logging
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger("sdq.tourism.operations")


def _run_tourism_sync(params, user_id, set_phase) -> Dict:
    """Fetch ONE open data (non-resident air arrivals) and persist the ITT for every year."""
    from modules.tourism_intel.service import backfill_scores, sincronizar_llegadas_mensuales

    set_phase("descargando llegadas de no residentes (ONE, datos.gob.do)")
    db = SessionLocal()
    try:
        set_phase("calculando ITT por año (tracción turística del destino RD)")
        resultado = backfill_scores(db)
        # EL FEED MENSUAL NO TUMBA EL ÍNDICE: el ITT ya quedó escrito y es anual. Si el BCRD no
        # responde, la corrida lo registra y el sensor de fuentes lo verá atrasar.
        set_phase("descargando la llegada mensual de no residentes (BCRD)")
        try:
            resultado = {**resultado, "llegadas_mensuales": sincronizar_llegadas_mensuales(db)}
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning("llegadas mensuales del BCRD no sincronizadas: %s", e, exc_info=True)
            resultado = {**resultado, "llegadas_mensuales": {"error": f"{type(e).__name__}: {e}"}}
        return resultado
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "one-tourism-sync", "Sincronizar turismo (ONE llegadas)",
        "Descarga los datos abiertos de la ONE (llegada de pasajeros vía aérea de no "
        "residentes por año y mercado de origen) desde datos.gob.do y persiste el Índice "
        "de Tracción Turística (ITT) del último año. Dato público real.",
        # Mensual: el BCRD sube la llegada de no residentes al cierre de cada mes. El ITT es anual
        # y rehacerlo cada mes es idempotente. ⚠️ En prod manda la agenda GUARDADA: hay que hacer
        # PUT /api/v1/operations/one-tourism-sync/schedule.
        _run_tourism_sync, default_interval_hours=720,
    ))


register()
