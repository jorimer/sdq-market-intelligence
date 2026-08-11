"""Banking-score console operations.

Defines this module's recurring runners and registers them into the shared
operation console (:mod:`shared.operations`). The console framework (status,
history, scheduler) is platform-wide; this module only owns its runners.
"""
import json
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
from shared.operations import Operation, register_operation


def _run_rescore(params, user_id, set_phase) -> Dict:
    from modules.banking_score.scoring.batch import score_all_periods
    db = SessionLocal()
    try:
        return score_all_periods(
            db,
            only_sib=bool(params.get("only_sib", True)),
            created_by=user_id,
            on_progress=lambda i, total, pe: set_phase(f"calculando {pe} ({i}/{total})"),
        )
    finally:
        db.close()


def _run_prune(params, user_id, set_phase) -> Dict:
    from modules.banking_score.sib_sync import prune_future_periods, prune_partial_latest_quarter
    db = SessionLocal()
    try:
        set_phase("podando trimestres futuros")
        future = prune_future_periods(db)
        set_phase("podando trimestre parcial (si lo hay)")
        partial = prune_partial_latest_quarter(db)
        return {"future": future, "partial": partial}
    finally:
        db.close()


def _run_purge_synthetic(params, user_id, set_phase) -> Dict:
    from modules.banking_score.sib_sync import purge_synthetic_data
    db = SessionLocal()
    try:
        set_phase("purgando datos sintéticos (source=manual) y ratings huérfanos")
        return purge_synthetic_data(db)
    finally:
        db.close()


def _run_recompute(params, user_id, set_phase) -> Dict:
    period = params.get("period")
    if not period:
        raise ValueError("Falta el período (YYYY-MM) para recomputar carteras.")
    from modules.banking_score.sib_sync import recompute_carteras_metrics

    def _ws(_db, **updates):  # adapter: route phase → op status
        ph = updates.get("phase")
        if ph:
            set_phase(ph)

    return recompute_carteras_metrics(period, write_status=_ws)


BACKTEST_REPORT_KEY = "backtest_report"


def _run_backtest(params, user_id, set_phase) -> Dict:
    """Recompute the Eje-1 backtest and persist the report (AppSetting)."""
    from modules.banking_score.validation.report import build_backtest_report
    db = SessionLocal()
    try:
        set_phase("derivando desenlaces y métricas de discriminación")
        rep = build_backtest_report(db)
        rep["generated_at"] = datetime.now(timezone.utc).isoformat()
        row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_REPORT_KEY).first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=BACKTEST_REPORT_KEY, value=payload, is_secret=False))
        db.commit()
        return {"gini": rep.get("gini"), "n_observations": rep.get("n_observations"),
                "n_events": rep.get("n_events"), "monotonic": rep.get("monotonic")}
    finally:
        db.close()


def _run_sib_historical_load(params, user_id, set_phase) -> Dict:
    """Carga el ledger histórico de la SB (Cronología SB, 1947→) y deriva los financials.

    Descarga los 7 CSV públicos, los carga a ``sib_historical_ledger`` (idempotente,
    replace por archivo) y reconstruye ``sib_historical_financials`` vía el crosswalk.
    Corre server-side (alcanza la DB interna, descarga en el servidor). Bajo demanda: el
    snapshot de la SB se actualiza esporádicamente; re-correr re-descarga ~518 MB.
    """
    from modules.banking_score.external import sib_historical_client as hist
    from modules.banking_score import sib_historical_crosswalk as xw
    db = SessionLocal()
    try:
        loaded: Dict[str, int] = {}
        n = len(hist.FILES)
        for i, rec in enumerate(hist.FILES, 1):
            name = hist.source_file_name(rec)
            set_phase(f"descargando y cargando {name} ({i}/{n})")
            try:
                loaded[name] = hist.load_file(db, rec)
            except Exception as e:  # noqa: BLE001 — un archivo no debe abortar el resto
                loaded[name] = -1
                set_phase(f"{name} falló: {e}")
        total = sum(v for v in loaded.values() if v and v > 0)
        set_phase(f"derivando financials por entidad ({total:,} filas en el ledger)")
        derived = xw.derive_all(db)
        return {"ledger_rows": total, "derived_rows": derived, "files": loaded}
    finally:
        db.close()


def _run_perfil_sdq(params, user_id, set_phase) -> Dict:
    """Recomputa Perfil SDQ sobre TODO el histórico, sin re-escorear indicadores.

    Distinto de `rescore`: parte de los sub-componentes ya persistidos y solo reagrega, así
    que es rápido y —lo importante— **no genera acciones de rating**. Recalcular el histórico
    entero con `rescore` produciría movimientos de tier entre períodos que no ocurrieron.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.perfil_backfill import backfill_perfil_sdq

    db = SessionLocal()
    try:
        return backfill_perfil_sdq(db, set_phase=set_phase)
    finally:
        db.close()


def _run_reetiquetar_acciones(params, user_id, set_phase) -> Dict:
    """Re-etiqueta el histórico de acciones a Perfil SDQ (spec §9, decisión del dueño).

    No re-escorea: deriva las transiciones por eje de las bandas ya persistidas. Idempotente.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.acciones_por_eje import reetiquetar

    db = SessionLocal()
    try:
        return reetiquetar(db, set_phase=set_phase)
    finally:
        db.close()


def _run_dedup_acciones(params, user_id, set_phase) -> Dict:
    """Deduplica `rating_actions`. Por defecto SIMULA — hay que pasar `ejecutar: true`.

    Un borrado en producción se mira antes de correrlo, así que el valor por defecto cuenta
    y no toca nada.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.dedup_acciones import deduplicar

    db = SessionLocal()
    try:
        return deduplicar(db, set_phase=set_phase,
                          ejecutar=bool((params or {}).get("ejecutar")))
    finally:
        db.close()


def register() -> None:
    """Register banking-score operations into the shared console (idempotent)."""
    register_operation(Operation(
        "perfil-sdq-backfill", "Recomputar Perfil SDQ (histórico)",
        "Calcula Ejecución y Resiliencia para todos los períodos desde los sub-componentes "
        "ya guardados. No re-escorea indicadores ni genera acciones de rating.",
        _run_perfil_sdq, default_interval_hours=0,
    ))
    register_operation(Operation(
        "dedup-acciones", "Deduplicar acciones de rating",
        "Deja UNA acción por entidad y período. Por defecto SIMULA: devuelve el conteo sin "
        "borrar. Para ejecutar hay que pasar params {\"ejecutar\": true}.",
        _run_dedup_acciones, default_interval_hours=0,
    ))
    register_operation(Operation(
        "reetiquetar-acciones", "Re-etiquetar acciones a Perfil SDQ (histórico)",
        "Desdobla cada acción de rating en sus dos transiciones de eje, leyéndolas de las "
        "bandas ya persistidas. NO re-escorea ni genera acciones nuevas.",
        _run_reetiquetar_acciones, default_interval_hours=0,
    ))
    register_operation(Operation(
        "rescore", "Recalcular ratings",
        "Recalcula los ratings desde los datos existentes, sin descargar del SIB.",
        _run_rescore, default_interval_hours=168,
    ))
    register_operation(Operation(
        "prune-future", "Eliminar trimestres futuros",
        "Borra datos y ratings de trimestres aún no cerrados (period_end > hoy).",
        _run_prune, default_interval_hours=168,
    ))
    register_operation(Operation(
        "purge-synthetic", "Purgar datos sintéticos (seed)",
        "Borra los datos sembrados sintéticos (source=manual) y los ratings/acciones "
        "que queden huérfanos. El catálogo de entidades y todo dato real "
        "(SIB/SIMBAD/CSV) quedan intactos. Sella el seed: la app solo puntúa dato real. "
        "Correr cuando: quieras sellar el paso de datos de siembra a solo dato real (una vez).",
        _run_purge_synthetic, default_interval_hours=0,
    ))
    register_operation(Operation(
        "recompute-carteras", "Recomputar carteras",
        "Re-descarga las carteras de crédito de un trimestre y actualiza concentración/mora. "
        "Correr cuando: haya que recomputar la cartera de un trimestre puntual (indicá el período).",
        _run_recompute, default_interval_hours=0, needs_params=["period"],
    ))
    register_operation(Operation(
        "backtest", "Backtest del rating",
        "Recalcula la validación de discriminación del rating (Gini + curva de distress por tier).",
        _run_backtest, default_interval_hours=720,
    ))
    register_operation(Operation(
        "sib-historical-load", "Cargar histórico SIB (1947→)",
        "Descarga los CSV históricos de la SB (Cronología SB) y carga el ledger crudo "
        "por-entidad mensual (balance 1947→, resultados 1996→), luego deriva los financials. "
        "Bajo demanda (~518 MB): correr cuando la SB publique un snapshot nuevo.",
        _run_sib_historical_load, default_interval_hours=0,
    ))


register()
