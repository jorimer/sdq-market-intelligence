"""Pension-intel console operations — SIPEN sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.validation.frescura import MotorValidacion, registrar_motor
from shared.validation.control_tamano import ControlDeTamano

BACKTEST_KEY = "pension_backtest_report"

# Las tres series que el backtest del ISA consume (solvencia + rentabilidad).
_SERIES_BACKTEST = ("patrimonio", "activos_totales", "rentabilidad_nominal_anual")


def huella_backtest(db) -> Dict:
    """Estado del insumo del backtest del ISA: las series por AFP que lo alimentan."""
    from sqlalchemy import func

    from modules.pension_intel.models.models import PensionSeries

    r = (db.query(func.count(PensionSeries.id), func.max(PensionSeries.period),
                  func.sum(PensionSeries.value))
         .filter(PensionSeries.series_code.in_(_SERIES_BACKTEST),
                 PensionSeries.entity_slug.isnot(None)).one())
    return {"series_n": r[0], "series_hasta": r[1], "series_suma": r[2]}


def persistir_backtest(db, rep: Dict) -> Dict:
    """Sella y persiste el reporte del backtest del ISA. Una sola puerta de escritura."""
    import json as _json

    from shared.settings.models import AppSetting
    from shared.validation.frescura import sellar

    sellar(rep, "pension_intel", db)
    row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_KEY).first()
    payload = _json.dumps(rep, ensure_ascii=False)
    if row:
        row.value, row.is_secret = payload, False
    else:
        db.add(AppSetting(key=BACKTEST_KEY, value=payload, is_secret=False))
    db.commit()
    return rep


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


def _run_pension_backtest(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.validation.backtest import build_backtest_report
    db = SessionLocal()
    try:
        set_phase("Derivando observaciones y computando Gini (IC bootstrap)")
        rep = persistir_backtest(db, build_backtest_report(db))
        sig = rep.get("signals") or {}
        return {"computed": rep.get("computed"), "headline_gini": rep.get("headline_gini"),
                "headline_signal": rep.get("headline_signal"),
                "solvency": (sig.get("solvency") or {}), "return": (sig.get("return") or {})}
    finally:
        db.close()


def _run_financials_history_sync(params, user_id, set_phase) -> Dict:
    from modules.pension_intel.financials_sync import sipen_financials_history_sync
    p = params or {}
    db = SessionLocal()
    try:
        return sipen_financials_history_sync(
            db, set_phase=set_phase,
            since_year=int(p.get("since_year") or 2010),
            annual=bool(p.get("annual", True)),
            only_slug=p.get("only_slug") or None,
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
        "On-demand (no auto-agendada). Correr cuando: quieras redescubrir qué publica SIPEN "
        "hoy (diagnóstico, no escribe en la base).",
        _run_sipen_discovery, default_interval_hours=0,  # on-demand: diagnóstico read-only
    ))
    register_operation(Operation(
        "sipen-audited-probe", "Sondear estados auditados de una AFP (read-only)",
        "Sondea a fondo los estados financieros AUDITADOS de UNA AFP (param opcional "
        "'slug', default afp_popular): cuántos archivos por año (anual vs mensual) con sus "
        "URLs reales, y una extracción de PRUEBA del archivo más antiguo y el más reciente "
        "(patrimonio/activos/AUM/comisiones) SIN persistir. Diagnóstico de la Fase 1 para "
        "escribir el crawler de auditados sobre hechos. Corre desde Railway. On-demand. "
        "Correr cuando: quieras sondear los estados auditados de una AFP (diagnóstico, no persiste).",
        _run_sipen_audited_probe, default_interval_hours=0, needs_params=None,
    ))
    register_operation(Operation(
        "sipen-sync", "Sincronizar pensiones (SIPEN)",
        "Ingiere las estadísticas del sistema dominicano de pensiones (SIPEN): "
        "series nacionales (rentabilidad, comisiones) y por AFP, más un snapshot "
        "del sistema. Dato público real (muestra citada en F0; canales live "
        "—CKAN/XLSX/boletín— en fases siguientes). Trimestral.",
        _run_sipen_sync, default_interval_hours=2160,  # trimestral → cadencia larga
        triggers=["pension-backtest"],  # rentabilidad nueva → re-validar el ISA
    ))
    register_operation(Operation(
        "sipen-financials-sync", "Sincronizar estados financieros AFP (SIPEN)",
        "Descarga los estados financieros de las AFP del portal de SIPEN (/descarga, "
        "PDF/XLSX), los extrae con el motor AI-native de estados financieros (reuso del "
        "de la SIB) y persiste patrimonio/activos por AFP → activa la dimensión de "
        "SOLVENCIA del ISA y, con ella, la banda absoluta. Corre desde Railway (egress "
        "de IPs estáticas + UA de navegador). También hay carga manual en la sección Datos.",
        _run_financials_sync, default_interval_hours=2160,  # trimestral
        triggers=["pension-backtest"],  # solvencia nueva → re-validar el ISA
    ))
    register_operation(Operation(
        "sipen-financials-history-sync", "Ingerir historia de estados AUDITADOS (SIPEN)",
        "Ingiere la HISTORIA de estados financieros AUDITADOS por AFP desde 2010: el cierre "
        "de diciembre de cada año (estado anual auditado) + el último mes disponible, por las "
        "7 AFP → serie de solvencia (patrimonio/activos) con trayectoria. Extrae con el motor "
        "AI-native y recalcula el ISA UNA vez al final. Params: since_year (2010), annual "
        "(true). Corre desde Railway; best-effort por archivo; idempotente. On-demand. "
        "Correr cuando: haga falta (re)ingerir el histórico de auditados de las AFP (backfill "
        "puntual con OCR+IA), típicamente antes de un pension-backtest.",
        _run_financials_history_sync, default_interval_hours=0,
        triggers=["pension-backtest"],  # es el insumo del Gate E: re-validar al terminar
    ))
    register_operation(Operation(
        "pension-backtest", "Backtest de validación del ISA (resultado-proxy)",
        "Valida el poder discriminante del ISA contra un resultado SUAVE (subdesempeño "
        "relativo vs. mediana del panel), ya que ninguna AFP ha fallado: señal solvencia "
        "(patrimonio/activos, anual) y señal rentabilidad (mensual, N alta). Computa Gini + "
        "IC bootstrap + calibración por quintil y persiste el reporte; el estado de validación "
        "(G5) lo lee. Sube G5 de 0.50 solo si el IC del Gini es positivo. On-demand. "
        "Correr cuando: revalides el ISA (nuevos períodos o cambio de modelo); requiere el "
        "history-sync antes.",
        _run_pension_backtest, default_interval_hours=0,
    ))
    registrar_motor(MotorValidacion(
        eje="pension_intel", operacion="pension-backtest", clave=BACKTEST_KEY,
        partes=huella_backtest,
        disparado_por=("sipen-sync", "sipen-financials-sync", "sipen-financials-history-sync"),
        control_de_tamano=ControlDeTamano(
            motivo="no_medido", variable="patrimonio del fondo administrado (AUM)",
            nota="son 7 AFP y el panel es chico, pero el tamaño del fondo es justamente lo "
                 "que separa a las dos grandes del resto: el control corresponde"),
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
