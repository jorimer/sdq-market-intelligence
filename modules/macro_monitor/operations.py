"""Macro-monitor console operations — registers the fiscal pulse sync.

Persists the fiscal dimension of Eje 2 (Hacienda Estado de Operaciones + DGII
recaudación) into MacroSeries, triggerable/monitorable/schedulable from the shared
operation console (Gate F).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_fiscal_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_monitor.service import fiscal_sync
    db = SessionLocal()
    try:
        return fiscal_sync(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "fiscal-sync", "Sincronizar pulso fiscal (Hacienda + DGII)",
        "Trae las cuentas fiscales del Estado de Operaciones del Ministerio de "
        "Hacienda (ingresos, gastos y déficit/superávit, mensual desde 2000) y la "
        "recaudación efectiva por grupo de impuesto de la DGII, y las persiste como "
        "series fiscales del macro (Eje 2). Mensual.",
        _run_fiscal_sync, default_interval_hours=720,
    ))


register()
