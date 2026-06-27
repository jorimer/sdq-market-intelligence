"""Pension-intel console operations — SIPEN sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_sipen_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.sipen_sync import sipen_pension_sync
    db = SessionLocal()
    try:
        return sipen_pension_sync(
            db, set_phase=set_phase,
            only_latest=bool((params or {}).get("only_latest")),
        )
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "sipen-sync", "Sincronizar pensiones (SIPEN)",
        "Ingiere las estadísticas del sistema dominicano de pensiones (SIPEN): "
        "series nacionales (rentabilidad, comisiones) y por AFP, más un snapshot "
        "del sistema. Dato público real (muestra citada en F0; canales live "
        "—CKAN/XLSX/boletín— en fases siguientes). Trimestral.",
        _run_sipen_sync, default_interval_hours=2160,  # trimestral → cadencia larga
    ))


register()
