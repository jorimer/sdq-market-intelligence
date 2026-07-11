"""Operaciones de consola de productos: recálculo de readiness + pre-calentado de caché.

Decisión 2026-06-23: el readiness se recalcula por evento (`*.updated`) + botón
manual. Esta operación expone el recálculo manual en la consola de Operaciones (y un
intervalo semanal opcional como red de seguridad, deshabilitado por defecto).
"""
import asyncio
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


def _run_prewarm_report_cache(params, user_id, set_phase) -> Dict:
    from shared.products.prewarm import prewarm_report_cache
    # El cliente Anthropic es síncrono/bloqueante; el motor lo mueve a un hilo (to_thread) y
    # acota la concurrencia con un semáforo. Aquí abrimos un event loop propio (el runner de
    # operaciones corre en su propio hilo daemon, sin loop previo) para el warm async.
    db = SessionLocal()
    try:
        return asyncio.run(prewarm_report_cache(db, set_phase=set_phase))
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

register_operation(Operation(
    name="prewarm-report-cache",
    label="Pre-calentar caché de reportes",
    description="Genera por adelantado y cachea las narrativas IA de los productos "
                "PUBLICADOS (niveles Insight y Deep Dive, todos sus ámbitos, en español), "
                "para que hasta la 1ª descarga sea instantánea. Idempotente por fingerprint: "
                "solo paga generación IA cuando el dato cambió (si no, HIT barato). Agendable; "
                "conviene correrla tras los syncs que refrescan datos.",
    runner=_run_prewarm_report_cache,
    default_interval_hours=24,  # diaria: barata en régimen (casi todo HIT), mantiene la caché tibia
))
