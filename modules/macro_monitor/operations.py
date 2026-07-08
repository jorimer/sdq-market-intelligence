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


def _run_bcrd_comunicados_sync(params, user_id, set_phase) -> Dict:
    """Descubre e ingiere los comunicados de política monetaria (decisiones de TPM) del BCRD,
    con la decisión estructurada + digest IA del racional. Idempotente por artículo (omite
    los ya ok salvo force=true).

    Params: ``limit`` (default 12, recurrente). ``all=true`` hace el backfill de TODA la
    trayectoria histórica (GetArticles) con SOLO dato estructurado, dejando el digest IA para
    los ``digest_limit`` más recientes (default 24) — barato: sin IA para el histórico."""
    from modules.macro_monitor.comunicados import service as com_service
    from modules.macro_monitor.comunicados import source as com_source
    db = SessionLocal()
    try:
        p = params or {}
        if p.get("all"):
            return com_service.ingest_comunicados(
                db, limit=None, digest_limit=int(p.get("digest_limit", 24)),
                force=bool(p.get("force")), list_fn=com_source.list_all_comunicados,
                set_phase=set_phase)
        return com_service.ingest_comunicados(
            db, limit=int(p.get("limit") or 12), force=bool(p.get("force")),
            set_phase=set_phase)
    finally:
        db.close()


def _run_tpm_model_train(params, user_id, set_phase) -> Dict:
    """Entrena el modelo de predicción de TPM (regla de Taylor + clasificador XGBoost),
    corre el backtest time-series y persiste modelo + reporte en AppSetting. Además mantiene
    el track record EN VIVO: (1) puntúa el pronóstico pendiente contra las decisiones ya
    conocidas, (2) re-entrena, (3) congela un pronóstico nuevo para la próxima decisión.

    Pesado (≈100 reentrenamientos en el backtest expanding-window) → va por la operación,
    no por endpoint síncrono. Sirve el forecast en /comunicados/forecast."""
    from modules.macro_monitor.tpm_modeling import ledger, service as tpm_service
    db = SessionLocal()
    try:
        set_phase("puntuando pronósticos pendientes vs decisiones reales")
        scored = ledger.score_pending(db)
        result = tpm_service.train_and_persist(db, trained_by=user_id, set_phase=set_phase)
        set_phase("registrando pronóstico en vivo para la próxima decisión")
        snapshot = ledger.snapshot_forecast(db)
        result["ledger"] = {"scored": scored, "snapshot": snapshot}
        return result
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
    register_operation(Operation(
        "bcrd-comunicados-sync", "Ingerir comunicados de política monetaria (TPM, digest IA)",
        "Descubre los comunicados de política monetaria del BCRD (cada decisión de TPM de "
        "la Junta Monetaria, HTML de la Sala de Prensa), deriva la decisión de forma "
        "determinista (sentido + nivel resultante) y genera un digest de IA del racional, "
        "ruteado a Macro/Banca. Idempotente (omite artículos ya ingeridos salvo "
        "force=true). Mensual — es la señal más oportuna del BCRD.",
        _run_bcrd_comunicados_sync, default_interval_hours=720,
        triggers=["tpm-model-train"],  # dato nuevo de decisiones → reentrena el modelo
    ))
    register_operation(Operation(
        "tpm-model-train", "Entrenar modelo de predicción de TPM",
        "Construye el panel POINT-IN-TIME de decisiones de política monetaria + features "
        "macro del BCRD, estima la regla de reacción tipo Taylor (OLS interpretable) y el "
        "clasificador XGBoost (hold/cut/hike, con pesos por clase por el desbalance), corre "
        "el backtest time-series expanding-window (recall por clase vs baseline 'siempre "
        "mantener') y persiste modelo + backtest. Alimenta /comunicados/forecast. Re-entrenar "
        "tras ingerir comunicados o refrescar las series macro. Mensual.",
        _run_tpm_model_train, default_interval_hours=720,
    ))


register()
