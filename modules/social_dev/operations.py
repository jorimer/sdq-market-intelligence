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


def register() -> None:
    register_operation(Operation(
        "one-social-sync", "Sincronizar social (ONE · pobreza por región)",
        "Trae la tasa de pobreza monetaria (general y extrema) por las 10 regiones "
        "de desarrollo desde la ONE (2000-…) y la persiste para el índice de "
        "desarrollo (IDM).",
        _run_one_social_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))


register()
