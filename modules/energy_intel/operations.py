"""Energy-intel console operations — SIE power-sector resilience sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_sie_energy_sync(params, user_id, set_phase) -> Dict:
    """Fetch SIE open data (installed capacity + claims) and persist the IRSE."""
    from modules.energy_intel.service import compute_and_persist

    set_phase("descargando capacidad instalada y reclamaciones (SIE, datos.gob.do)")
    db = SessionLocal()
    try:
        set_phase("calculando IRSE (resiliencia del sector eléctrico)")
        return compute_and_persist(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "sie-energy-sync", "Sincronizar energía (SIE)",
        "Descarga los datos abiertos de la SIE (capacidad instalada del SENI y "
        "estadísticas de reclamaciones) desde datos.gob.do y persiste el Índice de "
        "Resiliencia del Sector Eléctrico (IRSE) del último año. Dato público real. "
        "La transición renovable es brecha declarada (pendiente conector OC-SENI).",
        _run_sie_energy_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
