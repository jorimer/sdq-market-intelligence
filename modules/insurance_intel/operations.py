"""Insurance-intel console operations — SIS market sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


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


register()
