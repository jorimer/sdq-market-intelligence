"""Sector-intel console operations — registers bcrd-sectores-sync.

Registers the BCRD value-added sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI alongside every other module's operations (Gate F from day one).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_bcrd_sectores_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import bcrd_sectores_sync
    db = SessionLocal()
    try:
        return bcrd_sectores_sync(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "bcrd-sectores-sync", "Sincronizar sectores (BCRD · valor agregado)",
        "Trae el valor agregado por actividad económica del BCRD (PIB por sectores "
        "de origen, base 2018): tamaño (share del VAB) y crecimiento real interanual "
        "para los ~17 sectores de la economía, y los persiste para el IAI.",
        _run_bcrd_sectores_sync, default_interval_hours=2160,  # cuentas nac. ~trimestral → trimestral
    ))


register()
