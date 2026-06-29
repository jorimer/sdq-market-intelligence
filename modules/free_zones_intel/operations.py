"""Free-zones-intel console operations — CNZFE attractiveness sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_cnzfe_sync(params, user_id, set_phase) -> Dict:
    """Fetch CNZFE open data (free-zone fundamentals) and persist the IZF for every year."""
    from modules.free_zones_intel.service import backfill_scores

    set_phase("descargando variables del sector zonas francas (CNZFE, datos.gob.do)")
    db = SessionLocal()
    try:
        set_phase("calculando IZF por año (atractividad del sector zonas francas)")
        return backfill_scores(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "cnzfe-free-zones-sync", "Sincronizar zonas francas (CNZFE)",
        "Descarga los datos abiertos de la CNZFE (variables del sector de zonas francas: "
        "exportaciones, inversión, empleos, empresas) desde datos.gob.do y persiste el "
        "Índice de Atractividad de Zonas Francas (IZF) del último año. Dato público real.",
        _run_cnzfe_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
