"""Macro-political-risk console operations — registers wgi-sync.

Owns the WGI sync runner and registers it into the shared operation console
(:mod:`shared.operations`), so it's triggerable / monitorable / schedulable from
the UI alongside every other module's operations.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_wgi_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.wgi_sync import wgi_sync
    db = SessionLocal()
    try:
        return wgi_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_wdi_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.wdi_sync import wdi_sync
    db = SessionLocal()
    try:
        return wdi_sync(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "wgi-sync", "Sincronizar WGI (Banco Mundial)",
        "Trae los 3 indicadores de gobernanza (rule of law / gov effectiveness / "
        "control of corruption) para el peer set regional y los persiste.",
        _run_wgi_sync, default_interval_hours=720,  # WGI es anual → cadencia larga
    ))
    register_operation(Operation(
        "wdi-sync", "Sincronizar WDI + IMF (macro)",
        "Trae los indicadores macro/externos (PIB, inflación, reservas, cuenta "
        "corriente, IED desde WDI; deuda y balance fiscal desde IMF WEO) para el "
        "peer set regional y los persiste.",
        _run_wdi_sync, default_interval_hours=720,  # anual → cadencia larga
    ))


register()
