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


def _run_financials_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.financials_sync import sipen_financials_sync
    db = SessionLocal()
    try:
        return sipen_financials_sync(
            db, set_phase=set_phase,
            only_latest=bool((params or {}).get("only_latest", True)),
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
    register_operation(Operation(
        "sipen-financials-sync", "Sincronizar estados financieros AFP (SIPEN)",
        "Descarga los estados financieros de las AFP del portal de SIPEN (/descarga, "
        "PDF/XLSX), los extrae con el motor AI-native de estados financieros (reuso del "
        "de la SIB) y persiste patrimonio/activos por AFP → activa la dimensión de "
        "SOLVENCIA del ISA y, con ella, la banda absoluta. Corre desde Railway (egress "
        "de IPs estáticas + UA de navegador). También hay carga manual en la sección Datos.",
        _run_financials_sync, default_interval_hours=2160,  # trimestral
    ))


register()
