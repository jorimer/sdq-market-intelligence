"""Telecom-intel console operations — INDOTEL telecom-development sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_indotel_telecom_sync(params, user_id, set_phase) -> Dict:
    """Fetch INDOTEL's latest quarterly bulletin and persist the IDT."""
    from modules.telecom_intel.service import compute_and_persist

    set_phase("descargando boletín trimestral de indicadores (INDOTEL)")
    db = SessionLocal()
    try:
        set_phase("calculando IDT (desarrollo telecom)")
        return compute_and_persist(db)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "indotel-telecom-sync", "Sincronizar telecom (INDOTEL)",
        "Descarga el boletín trimestral de indicadores de telecomunicaciones de "
        "INDOTEL (XLSX: líneas, suscripciones a internet, banda ancha, ingresos) y "
        "persiste el Índice de Desarrollo Telecom (IDT). Dato público real; el boletín "
        "público más reciente es 2022-Q1 (la frescura lo refleja honestamente).",
        _run_indotel_telecom_sync, default_interval_hours=2160,
    ))


register()
