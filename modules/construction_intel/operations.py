"""Construction-intel console operations — MIVHED + BCRD construction sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_construction_sync(params, user_id, set_phase) -> Dict:
    """Fetch MIVHED permits + BCRD construction growth and persist the ICC for every year."""
    from modules.construction_intel.service import backfill_scores

    set_phase("descargando licencias de construcción (MIVHED) y PIB construcción (BCRD)")
    db = SessionLocal()
    try:
        set_phase("calculando ICC por año (coyuntura del sector construcción)")
        return backfill_scores(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "mivhed-construction-sync", "Sincronizar construcción (MIVHED + BCRD)",
        "Descarga las licencias de construcción del MIVHED (datos.gob.do) y el crecimiento "
        "real del PIB de construcción del BCRD, y persiste el Índice de Construcción (ICC) "
        "del último año completo. Dato público real (permisos líder + producción efectiva).",
        _run_construction_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
