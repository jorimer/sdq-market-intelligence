"""Insurance-intel console operations — SIS market sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.validation.frescura import MotorValidacion, registrar_motor

BACKTEST_KEY = "insurance_backtest_report"

# Las cinco series que el backtest del ISF consume (solvencia cruzada + underwriting).
_SERIES_BACKTEST = ("patrimonio", "activos_totales", "siniestros_pagados",
                    "gastos_operativos", "primas_suscritas")


def huella_backtest(db) -> Dict:
    """Estado del insumo del backtest del ISF: las series auditadas que lo alimentan.

    Filtrada a las cinco series que el backtest usa y no al panel entero: una huella que se
    mueve con cualquier ingesta no relacionada marca obsoleto lo que no lo está, y una
    señal que grita de más se deja de mirar — que es la forma lenta de volver al problema.
    """
    from sqlalchemy import func

    from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

    r = (db.query(func.count(InsuranceSeries.id), func.max(InsuranceSeries.period),
                  func.sum(InsuranceSeries.value))
         .filter(InsuranceSeries.series_code.in_(_SERIES_BACKTEST)).one())
    # El roster también manda: una aseguradora que entra o sale del panel autorizado cambia
    # el universo del backtest sin tocar una sola serie.
    roster = (db.query(func.count(InsuranceEntity.id))
              .filter(InsuranceEntity.entity_type == "aseguradora").scalar())
    return {"series_n": r[0], "series_hasta": r[1], "series_suma": r[2], "roster_n": roster}


def persistir_backtest(db, rep: Dict) -> Dict:
    """Sella y persiste el reporte del backtest. Una sola puerta de escritura.

    Existe porque había DOS —la operación de consola y el POST de la API— y ninguna
    estampaba fecha: el de seguros era el único reporte del catálogo del que no se podía
    saber de cuándo era la cifra servida.
    """
    import json as _json

    from shared.settings.models import AppSetting
    from shared.validation.frescura import sellar

    sellar(rep, "insurance_intel", db)
    row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_KEY).first()
    payload = _json.dumps(rep, ensure_ascii=False)
    if row:
        row.value, row.is_secret = payload, False
    else:
        db.add(AppSetting(key=BACKTEST_KEY, value=payload, is_secret=False))
    db.commit()
    return rep


def _run_sis_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.sis_sync import sis_insurance_sync
    db = SessionLocal()
    try:
        mode = (params or {}).get("mode") or "live"
        return sis_insurance_sync(db, set_phase=set_phase, mode=mode)
    finally:
        db.close()


def _run_financials_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.financials_sync import sis_financials_sync
    db = SessionLocal()
    try:
        year = (params or {}).get("year")
        return sis_financials_sync(db, set_phase=set_phase, year=year)
    finally:
        db.close()


def _run_sisalril_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
    db = SessionLocal()
    try:
        mode = (params or {}).get("mode") or "live"
        return sisalril_sfs_sync(db, set_phase=set_phase, mode=mode)
    finally:
        db.close()


def _run_financials_history_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.financials_sync import sis_financials_history_sync
    db = SessionLocal()
    try:
        since = int((params or {}).get("since_year") or 2018)
        return sis_financials_history_sync(db, set_phase=set_phase, since_year=since)
    finally:
        db.close()


def _run_solvency_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.solvency_sync import solvency_sync
    db = SessionLocal()
    try:
        mode = (params or {}).get("mode") or "live"
        return solvency_sync(db, set_phase=set_phase, mode=mode)
    finally:
        db.close()


def _run_ars_sync(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.ars_sync import ars_sync
    db = SessionLocal()
    try:
        mode = (params or {}).get("mode") or "live"
        return ars_sync(db, set_phase=set_phase, mode=mode)
    finally:
        db.close()


def _run_backtest(params, user_id, set_phase) -> Dict:
    from modules.insurance_intel.validation.backtest import build_backtest_report
    db = SessionLocal()
    try:
        set_phase("Derivando observaciones y computando Gini (IC bootstrap)")
        rep = persistir_backtest(db, build_backtest_report(db))
        return {"computed": rep.get("computed"), "headline_gini": rep.get("headline_gini"),
                "headline_signal": rep.get("headline_signal")}
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "insurance-sync", "Sincronizar seguros (SIS · mercado)",
        "Ingiere las estadísticas del mercado asegurador dominicano publicadas por la "
        "Superintendencia de Seguros (SIS) vía datos.gob.do (CKAN): primas netas cobradas "
        "por ramo (mensual, 2020-2025) y el número de aseguradoras activas por ramo, más un "
        "snapshot del mercado. Descarga live de los XLSX del portal con respaldo al fixture "
        "citado si la red falla. Trata el año 2024 (duplicado de 2023 en la fuente) como no "
        "independiente. Dato público real. Trimestral.",
        _run_sis_sync, default_interval_hours=2160,  # trimestral → cadencia larga
    ))
    register_operation(Operation(
        "insurance-financials-sync", "Sincronizar estados auditados de aseguradoras (SIS)",
        "Descubre el último libro de Estados Financieros Auditados por compañía del portal de "
        "la SIS (Excel, una hoja por aseguradora), lo descarga y extrae con un parser "
        "determinístico y reconciliado (activo=pasivo+patrimonio o se descarta la hoja): "
        "patrimonio, activos, primas suscritas, siniestros pagados, reservas técnicas y "
        "liquidez por aseguradora. Siembra el roster, persiste las series por entidad y "
        "recalcula el Índice de Solidez de Aseguradora (ISF) con banda absoluta. Param opcional "
        "'year'. Corre desde Railway. Anual (los auditados salen por año).",
        _run_financials_sync, default_interval_hours=8760,  # anual
        triggers=["insurance-backtest"],  # dato auditado nuevo → re-validar el ISF
    ))
    register_operation(Operation(
        "sisalril-sfs-sync", "Sincronizar cobertura de salud SFS (SISALRIL/CNSS)",
        "Ingiere la serie nacional de afiliación al Seguro Familiar de Salud (SFS) por régimen "
        "—total, contributivo y subsidiado— publicada por CNSS/SISALRIL en datos.gob.do (CSV "
        "mensual, 2007–2026). Alimenta la lectura de cobertura de salud del pulso asegurador "
        "(sub-sector SISALRIL). Descarga live con respaldo al fixture citado. El rating de "
        "solidez de las ARS es una vía aparte diferida (financieros tras el portal REDATAM). "
        "Dato público real. Mensual.",
        _run_sisalril_sync, default_interval_hours=720,  # mensual
    ))
    register_operation(Operation(
        "ars-sync", "Sincronizar solidez de ARS (SISALRIL · BDFINAC)",
        "Ingiere los estados financieros regulatorios de las Administradoras de Riesgos de "
        "Salud (ARS) desde el Portal Estadístico de SISALRIL (base BDFINAC, endpoint REST de "
        "descarga): margen de solvencia (inversiones que avalan / requerido), ingreso y gasto "
        "en salud y beneficio neto por ARS. Siembra el roster, persiste las series y calcula el "
        "Índice de Solidez de ARS (ISARS): margen de solvencia, siniestralidad médica y "
        "resultado técnico. La solvencia patrimonial es brecha declarada (esquema no documentado "
        "del todo). Descarga live con respaldo al fixture citado. Dato público real. Mensual.",
        _run_ars_sync, default_interval_hours=720,  # mensual
    ))
    register_operation(Operation(
        "insurance-financials-history-sync", "Ingerir historia de estados AUDITADOS (SIS)",
        "Ingiere la HISTORIA de estados financieros auditados por compañía desde 2018 (era "
        ".xlsx, estructura estable): patrimonio, activos, primas, siniestros e ingresos/gastos "
        "por aseguradora y año → serie con trayectoria. Recalcula el ISF una vez al final. Es "
        "el insumo del backtest de validación (G5). Param opcional 'since_year'. Corre desde "
        "Railway; best-effort por año; idempotente. On-demand. Correr cuando: haga falta "
        "(re)ingerir el histórico de auditados de aseguradoras (backfill puntual), típicamente "
        "antes de un insurance-backtest.",
        _run_financials_history_sync, default_interval_hours=0,
        triggers=["insurance-backtest"],  # es el insumo del Gate E: re-validar al terminar
    ))
    register_operation(Operation(
        "insurance-solvency-sync", "Sincronizar índices de solvencia y liquidez (SIS · Art. 164)",
        "Descarga los Índices de Solvencia y Liquidez OFICIALES que publica la Superintendencia "
        "de Seguros por aseguradora (Ley 146-02, Cap. XII, Art. 164; Excel auditado/trimestral): "
        "índice de solvencia = patrimonio técnico ajustado / margen de solvencia mínima requerida "
        "(≥1 cumple), e índice de liquidez = disponibilidad libre / liquidez mínima requerida. "
        "Los cruza al roster (por clave de marca) y recalcula el ISF usando la solvencia y "
        "liquidez REGULATORIAS en vez de proxies. Trimestral.",
        _run_solvency_sync, default_interval_hours=2160,  # trimestral
    ))
    register_operation(Operation(
        "insurance-backtest", "Backtest de validación del ISF (resultado-proxy)",
        "Valida el poder discriminante del ISF contra un resultado SUAVE (subdesempeño técnico "
        "relativo vs. mediana del panel), ya que ninguna aseguradora ha quebrado. Señal cruzada "
        "solvencia→resultado técnico y persistencia de underwriting; Gini + IC bootstrap sobre "
        "la historia de auditados. Persiste el reporte; el estado de validación (G5) lo lee y "
        "sube de 0.60 solo si el IC del Gini es positivo. Requiere history-sync antes. On-demand. "
        "Correr cuando: revalides el ISF (nuevos períodos o cambio de modelo); requiere el "
        "history-sync antes.",
        _run_backtest, default_interval_hours=0,
    ))
    registrar_motor(MotorValidacion(
        eje="insurance_intel", operacion="insurance-backtest", clave=BACKTEST_KEY,
        partes=huella_backtest,
        disparado_por=("insurance-financials-sync", "insurance-financials-history-sync"),
    ))


register()
