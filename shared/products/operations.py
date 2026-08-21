"""Operaciones de consola de productos: recálculo de readiness.

Decisión 2026-06-23: el readiness se recalcula por evento (`*.updated`) + botón
manual. Esta operación expone el recálculo manual en la consola de Operaciones (y un
intervalo semanal opcional como red de seguridad, deshabilitado por defecto).

Decisión 2026-08-20: acá vivía también ``prewarm-report-cache``, el pre-calentado de la
caché de narrativas. Se ELIMINÓ —operación, motor y disparadores—: generaba informes que
nadie pidió y gastaba IA sola. Los informes se generan cuando alguien los descarga (la
primera descarga paga los 15-90 s; las siguientes son HIT de ``ProductReportCache``). No
volver a agregarlo sin una decisión explícita: lo vigila
``shared/products/tests/test_regla_sin_precalentado.py``.
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
