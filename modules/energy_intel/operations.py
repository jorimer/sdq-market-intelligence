"""Energy-intel console operations — SIE + ONE power-sector resilience sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_sie_energy_sync(params, user_id, set_phase) -> Dict:
    """Fetch SIE (capacity + claims) and ONE (generation mix) open data, persist IRSE.

    Backfill por año (cobertura plena 3/3): un score por cada año comparable, no solo
    el más reciente — así el selector de períodos del producto ofrece la serie real."""
    from modules.energy_intel.service import backfill_scores

    set_phase("descargando capacidad, reclamaciones (SIE) y generación por tecnología (ONE)")
    db = SessionLocal()
    try:
        set_phase("calculando IRSE por año (backfill de cobertura plena)")
        return backfill_scores(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "sie-energy-sync", "Sincronizar energía (SIE + ONE)",
        "Descarga datos abiertos de la SIE (capacidad instalada del SENI y reclamaciones) "
        "y de la ONE (generación por tecnología → penetración renovable) desde "
        "datos.gob.do, y persiste el Índice de Resiliencia del Sector Eléctrico (IRSE) "
        "del último año con sus 3 dimensiones. Dato público real.",
        _run_sie_energy_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
