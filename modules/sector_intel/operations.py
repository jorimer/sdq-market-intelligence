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


def _run_wgi_regulatory_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import wgi_regulatory_sync
    db = SessionLocal()
    try:
        return wgi_regulatory_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_sector_snapshot(params, user_id, set_phase) -> Dict:
    """Backfill the IAI/SGPS over EVERY real period (BCRD) and purge any score
    outside that set (no fixture/seed remnants), publishing sector.updated."""
    from modules.sector_intel.service import backfill_sector_scores
    db = SessionLocal()
    try:
        return backfill_sector_scores(db, set_phase=set_phase)
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
    register_operation(Operation(
        "wgi-sectorial-sync", "Sincronizar regulación (WGI · calidad regulatoria)",
        "Trae la calidad regulatoria nacional del Banco Mundial (WGI, percentil "
        "0-100, anual) y la persiste para la dimensión regulación del IAI. Es "
        "nacional: sube esa dimensión de rúbrica a dato real, igual para los 17 "
        "sectores (no cambia el ranking, mejora la procedencia). Corre antes del "
        "backfill del índice.",
        _run_wgi_regulatory_sync, default_interval_hours=2160,
    ))
    register_operation(Operation(
        "sector-snapshot", "Backfill del índice sectorial (IAI/SGPS)",
        "Calcula+persiste el IAI/SGPS de los ~17 sectores para TODOS los períodos "
        "con dato real del BCRD (2018-…), con exposición macro real solo en el "
        "período actual y rúbrica declarada para el resto, y purga cualquier score "
        "fuera del backfill (sin restos de fixture). Publica sector.updated.",
        _run_sector_snapshot, default_interval_hours=2160,
    ))


register()
