"""Social-dev console operations — registers one-social-sync.

Registers the ONE social sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI (Gate F).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_one_social_sync(params, user_id, set_phase) -> Dict:
    from modules.social_dev.social_sync import one_social_sync
    db = SessionLocal()
    try:
        return one_social_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_idm_snapshot(params, user_id, set_phase) -> Dict:
    from modules.social_dev.service import backfill_idm_scores
    db = SessionLocal()
    try:
        return backfill_idm_scores(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "one-social-sync", "Sincronizar social (ONE pobreza + WDI salud)",
        "Trae la tasa de pobreza monetaria por las 10 regiones de desarrollo (ONE, "
        "2000-…) y la esperanza de vida / mortalidad infantil nacionales (WDI), y "
        "las persiste para el índice de desarrollo (IDM).",
        _run_one_social_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))
    register_operation(Operation(
        "idm-snapshot", "Backfill del índice de desarrollo (IDM)",
        "Calcula+persiste el IDM de las 10 regiones para TODOS los períodos con dato "
        "real (pobreza ONE + salud WDI + rúbrica declarada), y purga cualquier score "
        "fuera del backfill (sin restos de fixture). Publica social.updated.",
        _run_idm_snapshot, default_interval_hours=2160,
    ))


register()
