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


def register() -> None:
    """Register banking-score operations into the shared console (idempotent)."""
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
        "(SIB/SIMBAD/CSV) quedan intactos. Sella el seed: la app solo puntúa dato real.",
        _run_purge_synthetic, default_interval_hours=0,
    ))
    register_operation(Operation(
        "recompute-carteras", "Recomputar carteras",
        "Re-descarga las carteras de crédito de un trimestre y actualiza concentración/mora.",
        _run_recompute, default_interval_hours=0, needs_params=["period"],
    ))
    register_operation(Operation(
        "backtest", "Backtest del rating",
        "Recalcula la validación de discriminación del rating (Gini + curva de distress por tier).",
        _run_backtest, default_interval_hours=720,
    ))


register()
