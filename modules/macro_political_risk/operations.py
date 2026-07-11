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


def _run_wgi2025_load(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.wgi2025_loader import ingest_wgi2025
    db = SessionLocal()
    try:
        return ingest_wgi2025(db, set_phase=set_phase)
    finally:
        db.close()


def _run_sovereign_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.sovereign_sync import sovereign_ratings_sync
    db = SessionLocal()
    try:
        return sovereign_ratings_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_gdelt_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.gdelt_sync import gdelt_sync
    db = SessionLocal()
    try:
        return gdelt_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_gdelt_bq_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.gdelt_bq_sync import gdelt_bq_sync
    db = SessionLocal()
    try:
        return gdelt_bq_sync(db, set_phase=set_phase)
    finally:
        db.close()


from shared.data.latam_peers import names as _peer_names
from shared.data.latam_peers import regions as _peer_regions

_PEER_NAMES = _peer_names()      # 24 países (fuente única shared.data.latam_peers)
_PEER_REGIONS = _peer_regions()


def _run_irmp_backtest(params, user_id, set_phase) -> Dict:
    """Rebuild the IRMP backtest (historical panel + GDELT instability outcome) and
    persist the report. Returns a compact summary for the console."""
    import json
    from datetime import datetime, timezone
    from shared.settings.models import AppSetting
    from modules.macro_political_risk.validation.report import build_backtest_report
    db = SessionLocal()
    try:
        set_phase("reconstruyendo panel histórico + outcomes de inestabilidad (GDELT/BQ)")
        rep = build_backtest_report()
        rep["generated_at"] = datetime.now(timezone.utc).isoformat()
        row = db.query(AppSetting).filter(AppSetting.key == "irmp_backtest_report").first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key="irmp_backtest_report", value=payload, is_secret=False))
        db.commit()
        gov = rep.get("governance", {})
        return {"gini_gobernanza": gov.get("gini"), "n_obs": gov.get("n_observations"),
                "n_eventos": gov.get("n_events"), "monotonic": gov.get("monotonic"),
                "spearman_vs_rating": rep.get("convergent_validity", {}).get("spearman_irmp_vs_rating")}
    finally:
        db.close()


def _run_irmp_history_backfill(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.irmp_backfill import backfill_irmp_history
    db = SessionLocal()
    try:
        return backfill_irmp_history(db, set_phase=set_phase)
    finally:
        db.close()


def _run_irmp_snapshot(params, user_id, set_phase) -> Dict:
    """Assemble the IRMP dataset (real + declared rubric) and compute+persist a
    snapshot for every peer country at the latest period, publishing irmp.updated.
    """
    from datetime import date
    from modules.macro_political_risk.service import assemble_irmp_dataset, compute_and_persist
    db = SessionLocal()
    try:
        set_phase("ensamblando dataset (real + rúbrica)")
        asm = assemble_irmp_dataset(db)
        dataset = asm["dataset"]
        period = asm["period"]
        # Require real data: an all-rubric snapshot isn't useful for the backtest
        # or the outlook overlay, and without a live period we'd otherwise date the
        # snapshot to a future year-end. Sync WGI/WDI first.
        if not asm["has_live"] or not (period and str(period).isdigit()):
            return {"snapshots": 0, "countries": len(dataset), "has_live": asm["has_live"],
                    "errors": ["sin dato real persistido; corre wgi-sync/wdi-sync primero"]}
        period_end = date(int(period), 12, 31)
        snaps, errors = 0, []
        for i, iso in enumerate(sorted(dataset), 1):
            set_phase(f"calculando IRMP {iso} ({i}/{len(dataset)})")
            try:
                compute_and_persist(
                    db, country_code=iso, dataset=dataset, period_end=period_end,
                    country_name=_PEER_NAMES.get(iso), region=_PEER_REGIONS.get(iso),
                )
                snaps += 1
            except Exception as e:  # noqa: BLE001 — one country must not abort the batch
                errors.append(f"{iso}: {e}")
        return {"snapshots": snaps, "period": str(period_end),
                "countries": len(dataset), "has_live": asm["has_live"], "errors": errors}
    finally:
        db.close()


def _run_irmp_cleanup(params, user_id, set_phase) -> Dict:
    """Borra los snapshots IRMP inválidos (breakdown con dimensiones de 0 variables) —
    lecturas de datasets parciales (E2E-F4). Idempotente: sin inválidos, no borra nada.
    """
    from modules.macro_political_risk.service import delete_invalid_snapshots
    db = SessionLocal()
    try:
        set_phase("buscando snapshots IRMP inválidos")
        return delete_invalid_snapshots(db)
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
    register_operation(Operation(
        "sovereign-ratings-sync", "Sincronizar rating soberano (Wikipedia)",
        "Trae la calificación soberana multi-agencia (S&P/Fitch/Moody's) del peer set "
        "desde Wikipedia y actualiza el store refrescable. Bajo la política 'S&P manda', "
        "solo el ancla S&P mueve el IRMP; Fitch/Moody's son contexto. Corre wdi-sync + "
        "irmp-snapshot después para propagar un cambio de nota.",
        _run_sovereign_sync, default_interval_hours=720,  # mensual (baja rotación)
    ))
    register_operation(Operation(
        "gdelt-sync", "Sincronizar eventos (GDELT · DOC API)",
        "Trae señales de eventos desde la DOC API de GDELT (tono → news_sentiment; "
        "cobertura de disturbios → unrest_shocks) para el peer set. Espaciada por "
        "el rate-limit de GDELT (~2 min). Frágil; preferir 'eventos (BigQuery)'.",
        _run_gdelt_sync, default_interval_hours=168,  # eventos = coyuntura → semanal
    ))
    register_operation(Operation(
        "gdelt-bq-sync", "Sincronizar eventos (GDELT · BigQuery)",
        "Trae los 3 indicadores de eventos (tono → news_sentiment; PROTEST → "
        "unrest_shocks; ECON_SANCTIONS → sanctions_signal) desde el dataset público "
        "de GDELT en BigQuery. Robusto (sin rate-limit). Requiere GCP_SA_JSON.",
        _run_gdelt_bq_sync, default_interval_hours=168,
    ))
    register_operation(Operation(
        "irmp-backtest", "Backtest del IRMP (validación)",
        "Reconstruye el IRMP histórico (2014-2024) y lo valida contra inestabilidad "
        "política realizada (eventos GDELT/BigQuery) + validez convergente vs rating. "
        "Direccional (N=5). Requiere GCP_SA_JSON.",
        _run_irmp_backtest, default_interval_hours=720,
    ))
    register_operation(Operation(
        "wgi-2025-load", "Cargar gobernanza WGI 2025 (histórico + fuentes)",
        "Ingesta el asset canónico de la revisión metodológica WGI 2025: serie "
        "absoluta 0-100 de 1996-2024 para las 6 dimensiones del panel regional, con "
        "intervalo de confianza, número de fuentes y el desglose de las 35 fuentes "
        "subyacentes. Reemplaza a 'wgi-sync' (API, 1 año, percentil viejo) como "
        "fuente autoritativa de gobernanza. Idempotente; on-demand.",
        _run_wgi2025_load, default_interval_hours=0,
    ))
    register_operation(Operation(
        "irmp-snapshot", "Calcular snapshot IRMP",
        "Ensambla el dataset (dato real + rúbrica declarada) y calcula+persiste el "
        "IRMP de cada país del peer set para el último período, publicando "
        "irmp.updated para los demás ejes.",
        _run_irmp_snapshot, default_interval_hours=720,
    ))
    register_operation(Operation(
        "irmp-history-backfill", "Backfill histórico del IRMP (trayectoria)",
        "Reconstruye y persiste un snapshot del IRMP por AÑO (2016 → año anterior) para "
        "todo el panel, dándole TRAYECTORIA al producto (antes: un solo corte). Dato 100% "
        "real por año: macro/externo (WDI+IMF), gobernanza (WGI), volatilidad regulatoria "
        "(std WGI), eventos (GDELT-BigQuery consultado POR AÑO) y proximidad electoral. "
        "Self-contained (no toca el snapshot en vivo ni el backtest). Requiere GCP_SA_JSON. "
        "RESUMIBLE: salta los años ya persistidos (sin gastar cuota de BigQuery), así la "
        "cadencia mensual va cerrando el hueco de años que la cuota gratuita corta (~3/mes) "
        "hasta completar; una vez completa, es un no-op barato.",
        _run_irmp_history_backfill, default_interval_hours=720,  # mensual → se auto-completa
    ))
    register_operation(Operation(
        "irmp-cleanup-invalid", "Limpiar snapshots IRMP inválidos",
        "Borra los snapshots IRMP con breakdown incompleto (alguna dimensión con 0 "
        "variables) — lecturas de datasets parciales que falsean el índice y el panel. "
        "Idempotente; on-demand.",
        _run_irmp_cleanup, default_interval_hours=0,
    ))


register()
