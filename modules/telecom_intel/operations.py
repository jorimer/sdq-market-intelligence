"""Telecom-intel console operations — INDOTEL telecom-development sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_itu_telecom_sync(params, user_id, set_phase) -> Dict:
    """Fetch ITU DataHub telecom penetration (live source) and persist the IDT.

    Backfill por año (cobertura plena 3/3): un IDT por cada año comparable de la serie
    ITU, no solo el más reciente — así el selector de períodos ofrece la serie real."""
    from modules.telecom_intel.service import backfill_scores_itu

    set_phase("descargando penetración telecom de RD (ITU DataHub API)")
    db = SessionLocal()
    try:
        set_phase("calculando IDT por año (backfill de cobertura plena)")
        return backfill_scores_itu(db)
    finally:
        db.close()


def _run_indotel_telecom_sync(params, user_id, set_phase) -> Dict:
    """Fetch INDOTEL's frozen 2022-Q1 bulletin and persist the IDT (histórico)."""
    from modules.telecom_intel.service import compute_and_persist

    set_phase("descargando boletín trimestral de indicadores (INDOTEL)")
    db = SessionLocal()
    try:
        set_phase("calculando IDT (desarrollo telecom)")
        return compute_and_persist(db)
    finally:
        db.close()


def register() -> None:
    # Fuente VIGENTE: ITU DataHub (INDOTEL congelado en 2022-Q1). Anual, API abierta.
    register_operation(Operation(
        "itu-telecom-sync", "Sincronizar telecom (ITU DataHub)",
        "Descarga la penetración telecom de RD de la API abierta de ITU DataHub "
        "(móvil, banda ancha móvil/fija, hogares con internet; per-100/%, fresca hasta "
        "2024) y persiste el Índice de Desarrollo Telecom (IDT). Reemplaza a INDOTEL, "
        "cuyo boletín público quedó congelado en 2022-Q1.",
        _run_itu_telecom_sync, default_interval_hours=8760,  # anual
    ))
    # Histórico/on-demand: el boletín INDOTEL (2022-Q1), conservado para trazabilidad.
    register_operation(Operation(
        "indotel-telecom-sync", "Sincronizar telecom (INDOTEL · histórico 2022-Q1)",
        "Descarga el boletín trimestral de INDOTEL (XLSX), congelado en 2022-Q1, y "
        "persiste su IDT. Histórico: la fuente vigente es ITU (itu-telecom-sync). "
        "Correr cuando: necesites recargar el histórico congelado de INDOTEL (rara vez).",
        _run_indotel_telecom_sync, default_interval_hours=0,  # on-demand (histórico)
    ))


register()
