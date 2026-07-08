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


def _run_bcrd_publications_sync(params, user_id, set_phase) -> Dict:
    """Ingiere la última edición de las publicaciones recurrentes del BCRD (Informe de
    Estabilidad Financiera, Economía Dominicana, IPOM) con digest IA. Idempotente:
    omite las ediciones ya ingeridas salvo force=true en params. (Espejo BCRD del
    ``one-publications-sync``.)"""
    from shared.publications import catalog as pub_catalog
    from shared.publications import service as pub_service
    db = SessionLocal()
    try:
        keys = pub_catalog.report_keys("BCRD")
        results = []
        for i, key in enumerate(keys, 1):
            set_phase(f"ingiriendo {key} ({i}/{len(keys)})")
            row = pub_service.ingest_report(db, key, force=bool((params or {}).get("force")))
            results.append({"report_key": key, "status": row.status if row else "unavailable",
                            "period": row.period if row else None})
        ok = sum(1 for r in results if r["status"] == "ok")
        return {"ingested_ok": ok, "total": len(keys), "results": results}
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
    register_operation(Operation(
        "bcrd-publications-sync", "Ingerir publicaciones BCRD (digest IA)",
        "Descarga la última edición de las publicaciones recurrentes del BCRD "
        "(Informe de Estabilidad Financiera, Informe de la Economía Dominicana e "
        "Informe de Política Monetaria), extrae el texto y genera un digest de IA "
        "ruteado a Macro/Banca. Idempotente (omite ediciones ya ingeridas salvo "
        "force=true en params). Mensual. La aparición de una edición nueva la vigila "
        "la auditoría de frescura de datos.",
        _run_bcrd_publications_sync, default_interval_hours=720,
    ))


register()
