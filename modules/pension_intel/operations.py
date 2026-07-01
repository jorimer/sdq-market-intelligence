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


def _run_cartera_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.cartera_sync import sipen_cartera_sync
    db = SessionLocal()
    try:
        return sipen_cartera_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_nav_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.nav_sync import sipen_nav_sync
    db = SessionLocal()
    try:
        n = int((params or {}).get("n_boletines") or 11)
        return sipen_nav_sync(db, set_phase=set_phase, n_boletines=n)
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
    register_operation(Operation(
        "sipen-cartera-sync", "Sincronizar cartera de inversiones (SIPEN)",
        "Descubre el último Boletín Trimestral de SIPEN (PDF), extrae el Cuadro 6.1 "
        "—composición de la cartera de inversiones de los fondos por emisor— con un "
        "parser determinístico que cuadra con el TOTAL (falla cerrado si no), y persiste "
        "las tenencias por emisor (Hacienda/BCRD/bancos/privados). Dato público real, sin "
        "OCR (el boletín es texto). Trimestral.",
        _run_cartera_sync, default_interval_hours=2160,  # trimestral
    ))
    register_operation(Operation(
        "sipen-nav-sync", "Sincronizar valor cuota / NAV (SIPEN)",
        "Encadena los últimos ~11 Boletines Trimestrales (PDF), extrae el Cuadro 6.4 "
        "—valor cuota mensual por AFP— y persiste la serie de NAV. Es el insumo de la "
        "dimensión de RIESGO del ISA: NAV mensual → retornos → volatilidad realizada. Dato "
        "público real, sin OCR. Trimestral (los boletines salen por trimestre).",
        _run_nav_sync, default_interval_hours=2160,  # trimestral
    ))


register()
