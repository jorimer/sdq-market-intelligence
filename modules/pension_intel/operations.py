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


def _run_sipen_discovery(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.sipen_discovery import sipen_discovery
    return sipen_discovery(set_phase=set_phase)


def _run_sipen_audited_probe(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.sipen_discovery import sipen_audited_probe
    slug = (params or {}).get("slug") or "afp_popular"
    return sipen_audited_probe(slug=slug, set_phase=set_phase)


def _run_financials_history_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.financials_sync import sipen_financials_history_sync
    p = params or {}
    db = SessionLocal()
    try:
        return sipen_financials_history_sync(
            db, set_phase=set_phase,
            since_year=int(p.get("since_year") or 2010),
            annual=bool(p.get("annual", True)),
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
        "sipen-discovery", "Descubrir cobertura SIPEN (read-only)",
        "Sondea CADA página de publicación de SIPEN (Estadística Previsional, Boletines, "
        "estados financieros interinos y AUDITADOS, CKAN) y devuelve un informe de qué "
        "archivos/cuadros/años existen hoy y cuáles NO ingerimos. NO escribe en la base, "
        "no ingiere, no muta scores — es puro diagnóstico (Fase 0 de la auditoría de "
        "cobertura). Establece la estructura real de la página de auditados antes de "
        "escribir su crawler. Corre desde Railway (egress estático + UA de navegador). "
        "On-demand (no auto-agendada).",
        _run_sipen_discovery, default_interval_hours=0,  # on-demand: diagnóstico read-only
    ))
    register_operation(Operation(
        "sipen-audited-probe", "Sondear estados auditados de una AFP (read-only)",
        "Sondea a fondo los estados financieros AUDITADOS de UNA AFP (param opcional "
        "'slug', default afp_popular): cuántos archivos por año (anual vs mensual) con sus "
        "URLs reales, y una extracción de PRUEBA del archivo más antiguo y el más reciente "
        "(patrimonio/activos/AUM/comisiones) SIN persistir. Diagnóstico de la Fase 1 para "
        "escribir el crawler de auditados sobre hechos. Corre desde Railway. On-demand.",
        _run_sipen_audited_probe, default_interval_hours=0, needs_params=None,
    ))
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
        "sipen-financials-history-sync", "Ingerir historia de estados AUDITADOS (SIPEN)",
        "Ingiere la HISTORIA de estados financieros AUDITADOS por AFP desde 2010: el cierre "
        "de diciembre de cada año (estado anual auditado) + el último mes disponible, por las "
        "7 AFP → serie de solvencia (patrimonio/activos) con trayectoria. Extrae con el motor "
        "AI-native y recalcula el ISA UNA vez al final. Params: since_year (2010), annual "
        "(true). Corre desde Railway; best-effort por archivo; idempotente. On-demand.",
        _run_financials_history_sync, default_interval_hours=0,
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
