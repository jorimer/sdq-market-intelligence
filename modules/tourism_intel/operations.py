"""Tourism-intel console operations — ONE arrivals traction sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_tourism_sync(params, user_id, set_phase) -> Dict:
    """Fetch ONE open data (non-resident air arrivals) and persist the ITT for every year."""
    from modules.tourism_intel.service import backfill_scores

    set_phase("descargando llegadas de no residentes (ONE, datos.gob.do)")
    db = SessionLocal()
    try:
        set_phase("calculando ITT por año (tracción turística del destino RD)")
        return backfill_scores(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "one-tourism-sync", "Sincronizar turismo (ONE llegadas)",
        "Descarga los datos abiertos de la ONE (llegada de pasajeros vía aérea de no "
        "residentes por año y mercado de origen) desde datos.gob.do y persiste el Índice "
        "de Tracción Turística (ITT) del último año. Dato público real.",
        _run_tourism_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
