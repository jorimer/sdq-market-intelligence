"""Sector-intel console operations — registers bcrd-sectores-sync.

Registers the BCRD value-added sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI alongside every other module's operations (Gate F from day one).
"""
import json
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

GATE_E_KEY = "sector_gate_e_report"


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


def _run_encft_empleo_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import encft_empleo_sync
    db = SessionLocal()
    try:
        return encft_empleo_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_enae_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import enae_sync
    db = SessionLocal()
    try:
        return enae_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_tss_salario_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import tss_salario_sync
    db = SessionLocal()
    try:
        return tss_salario_sync(db, set_phase=set_phase)
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


def _run_sector_gate_e(params, user_id, set_phase) -> Dict:
    """Run the Gate-E backtest (IAI_T vs Δempleo_{T+1} por rama) and persist it.
    Corre después de sector-snapshot + encft-empleo-sync (dependencia de orden)."""
    from modules.sector_intel.validation.report import gate_e_report
    from shared.settings.models import AppSetting

    set_phase("agregando IAI a ramas + outcome de empleo + IC medio anual (t)")
    db = SessionLocal()
    try:
        rep = gate_e_report(db)
        rep["generated_at"] = datetime.now(timezone.utc).isoformat()
        row = db.query(AppSetting).filter(AppSetting.key == GATE_E_KEY).first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=GATE_E_KEY, value=payload, is_secret=False))
        db.commit()
    finally:
        db.close()
    # Console summary surfaces the HEADLINE (mean yearly IC with its t-CI), not the
    # secondary pooled stat; n_obs and the growth-partial for context.
    return {"has_data": rep.get("has_data"), "mean_yearly_ic": rep.get("mean_yearly_ic"),
            "ic_ci": rep.get("ic_ci"), "n_years": rep.get("n_years"),
            "n_obs": rep.get("n_observations"),
            "spearman_partial_growth": rep.get("spearman_partial_growth"),
            "spearman_pooled": rep.get("spearman_pooled")}


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
        "encft-empleo-sync", "Sincronizar empleo (ONE · ENCFT por actividad)",
        "Trae el empleo (población ocupada) por actividad económica de la ONE "
        "(ENFT 2008-2016 / ENCFT 2017-2024), a su resolución real de 10 ramas, y lo "
        "persiste como panel histórico. Es el desenlace que valida el Gate E "
        "(crecimiento del empleo por rama) y el insumo del que luego se deriva la "
        "disponibilidad laboral del IAI. Anual.",
        _run_encft_empleo_sync, default_interval_hours=8760,  # serie anual → anual
    ))
    register_operation(Operation(
        "enae-sync", "Sincronizar actividad económica (ONE · ENAE estructural)",
        "Trae de la ENAE (ONE) los datos estructurales-financieros reales por sector "
        "(ingresos, costos y gastos, utilidad y rentabilidad, 2015-2022) a su "
        "resolución de 9 sectores encuestados, y los persiste como panel. Es dato "
        "real para des-rubricar las dimensiones de negocios (costo/margen) y sumar "
        "una señal de rentabilidad al IAI; cubre 9 de los 17 sectores (incluido "
        "Comercio). Anual.",
        _run_enae_sync, default_interval_hours=8760,  # serie anual → anual
    ))
    register_operation(Operation(
        "tss-salario-sync", "Sincronizar costo operativo (TSS · salario por actividad)",
        "Trae el salario promedio cotizable por actividad económica de la TSS (Power "
        "BI) y lo mapea a costo operativo por sector (los 17), insumo real de la "
        "dimensión negocios del IAI. Es una foto transversal del último año completo, "
        "aplicada a todos los períodos (como la calidad regulatoria WGI). Anual.",
        _run_tss_salario_sync, default_interval_hours=8760,
    ))
    register_operation(Operation(
        "sector-snapshot", "Backfill del índice sectorial (IAI/SGPS)",
        "Calcula+persiste el IAI/SGPS de los ~17 sectores para TODOS los períodos "
        "con dato real del BCRD (2018-…), con exposición macro real solo en el "
        "período actual y rúbrica declarada para el resto, y purga cualquier score "
        "fuera del backfill (sin restos de fixture). Publica sector.updated.",
        _run_sector_snapshot, default_interval_hours=2160,
    ))
    register_operation(Operation(
        "sector-gate-e", "Backtest sectorial (Gate E · empleo formal)",
        "Valida que el IAI en T ordena el crecimiento del empleo formal por rama en "
        "T+1 (IC de rango de Spearman, panel ENCFT a 10 ramas), controlando por el "
        "crecimiento del sector para acotar la circularidad. Direccional, se reporta "
        "con su n e IC. Corre después de sector-snapshot y encft-empleo-sync.",
        _run_sector_gate_e, default_interval_hours=0,  # on-demand
    ))


register()
