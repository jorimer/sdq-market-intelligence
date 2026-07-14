"""Construction-intel console operations — MIVHED + BCRD + ONE construction sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_construction_sync(params, user_id, set_phase) -> Dict:
    """Fetch MIVHED permits + BCRD growth + ONE valor tasado por tipología, persist the ICC."""
    from modules.construction_intel.service import backfill_scores

    set_phase("descargando MIVHED (licencias) + BCRD (PIB) + ONE (valor tasado por tipología)")
    db = SessionLocal()
    try:
        set_phase("calculando ICC por año (coyuntura del sector construcción)")
        return backfill_scores(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "mivhed-construction-sync", "Sincronizar construcción (MIVHED + BCRD + ONE)",
        "Descarga las licencias de construcción del MIVHED (datos.gob.do), el crecimiento "
        "real del PIB de construcción del BCRD y el valor tasado por tipología de la ONE "
        "(one.gob.do), y persiste el Índice de Construcción (ICC) del último año completo. "
        "Dato público real (permisos líder + producción efectiva + valor tasado autoritativo).",
        _run_construction_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
