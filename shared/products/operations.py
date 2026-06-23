"""Operación de consola: recálculo manual del readiness de productos.

Decisión 2026-06-23: el readiness se recalcula por evento (`*.updated`) + botón
manual. Esta operación expone el recálculo manual en la consola de Operaciones (y un
intervalo semanal opcional como red de seguridad, deshabilitado por defecto).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.products.service import recompute_readiness


def _run_recompute(params, user_id, set_phase) -> Dict:
    db = SessionLocal()
    try:
        set_phase("recalculando readiness de los 10 sectores × 3 niveles")
        return recompute_readiness(db)
    finally:
        db.close()


register_operation(Operation(
    name="products-readiness-recompute",
    label="Recalcular readiness de productos",
    description="Recalcula el readiness G1-G5 de los 10 sectores × 3 niveles desde las "
                "señales reales del contrato. Recálculo por evento + manual (no agendado).",
    runner=_run_recompute,
    default_interval_hours=168,  # red de seguridad semanal (deshabilitada por defecto)
))
