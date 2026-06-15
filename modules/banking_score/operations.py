"""Consola de Operación — operaciones recurrentes con estado + historial en DB.

Generaliza el patrón de estado de ``sib_sync`` (un JSON por operación en la tabla
KV ``AppSetting``, bajo ``op_status:{nombre}``) para que las operaciones que antes
eran curl-only (rescore, prune-future, recompute-carteras) sean disparables,
monitoreables y auditables desde la UI por un humano no-técnico.

- Estado en vivo: compartido entre workers (DB), con heartbeat para detectar
  cuelgues. Cada operación corre en un hilo daemon (igual que el recompute legacy).
- Historial: cada corrida deja una fila en ``operation_runs`` (origen, usuario,
  inicio/fin, resultado), para auditoría.
- El estado es la fuente de verdad; sobrevive reinicios del worker.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
from modules.banking_score.models.models import OperationRun

logger = logging.getLogger("sdq.operations")

_STALE_SECONDS = 30 * 60
_lock = threading.Lock()


def _spawn(target: Callable[[], None]) -> None:
    """Run *target* in a background daemon thread. Indirection so tests can run
    the worker synchronously."""
    threading.Thread(target=target, daemon=True).start()

_DEFAULT_STATUS: Dict = {
    "is_running": False,
    "phase": "",
    "started_at": None,
    "last_run": None,
    "last_result": None,
    "error": None,
    "heartbeat": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt():
    """Naive UTC for DateTime columns (Postgres TIMESTAMP WITHOUT TZ + SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(op: str) -> str:
    return f"op_status:{op}"


# ── Per-operation status (AppSetting KV) ──────────────────────────

def _read_status(db: Session, op: str) -> Dict:
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _key(op)).first()
    except Exception:  # noqa: BLE001 — table may not exist yet (pre-migration/tests)
        db.rollback()
        return dict(_DEFAULT_STATUS)
    if row and row.value:
        try:
            return {**_DEFAULT_STATUS, **json.loads(row.value)}
        except (ValueError, TypeError):
            pass
    return dict(_DEFAULT_STATUS)


def write_status(db: Session, op: str, **updates) -> Dict:
    st = _read_status(db, op)
    st.update(updates)
    st["heartbeat"] = _now()
    payload = json.dumps(st)
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _key(op)).first()
        if row:
            row.value = payload
            row.is_secret = False
        else:
            db.add(AppSetting(key=_key(op), value=payload, is_secret=False))
        db.commit()
    except Exception:  # noqa: BLE001 — status must never break the run
        db.rollback()
    return st


def get_status(db: Session, op: str) -> Dict:
    st = _read_status(db, op)
    ref = st.get("heartbeat") or st.get("started_at")
    if st.get("is_running") and ref:
        try:
            last = datetime.fromisoformat(ref)
            if (datetime.now(timezone.utc) - last).total_seconds() > _STALE_SECONDS:
                st = write_status(db, op, is_running=False, phase="(interrumpido)")
        except (ValueError, TypeError):
            pass
    return st


# ── Runners — each owns its own DB session and reports phase ───────
# Signature: runner(params: dict, user_id: str | None, set_phase: Callable[[str], None]) -> dict

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
    from modules.banking_score.sib_sync import prune_future_periods
    db = SessionLocal()
    try:
        set_phase("podando trimestres futuros")
        return prune_future_periods(db)
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
        rep["generated_at"] = _now()
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


# ── Operation registry ────────────────────────────────────────────

class Operation:
    def __init__(self, name: str, label: str, description: str, runner: Callable,
                 default_interval_hours: int, needs_params: Optional[List[str]] = None):
        self.name = name
        self.label = label
        self.description = description
        self.runner = runner
        self.default_interval_hours = default_interval_hours
        self.needs_params = needs_params or []


OPERATIONS: Dict[str, Operation] = {
    "rescore": Operation(
        "rescore", "Recalcular ratings",
        "Recalcula los ratings desde los datos existentes, sin descargar del SIB.",
        _run_rescore, default_interval_hours=168,
    ),
    "prune-future": Operation(
        "prune-future", "Eliminar trimestres futuros",
        "Borra datos y ratings de trimestres aún no cerrados (period_end > hoy).",
        _run_prune, default_interval_hours=168,
    ),
    "recompute-carteras": Operation(
        "recompute-carteras", "Recomputar carteras",
        "Re-descarga las carteras de crédito de un trimestre y actualiza concentración/mora.",
        _run_recompute, default_interval_hours=0, needs_params=["period"],
    ),
    "backtest": Operation(
        "backtest", "Backtest del rating",
        "Recalcula la validación de discriminación del rating (Gini + curva de distress por tier).",
        _run_backtest, default_interval_hours=720,
    ),
}


# ── History ───────────────────────────────────────────────────────

def _record_run(db: Session, op: str, origin: str, user_id, status: str,
                started_at, finished_at=None, summary=None, error=None) -> str:
    run = OperationRun(
        operation=op, origin=origin, triggered_by=user_id, status=status,
        started_at=started_at, finished_at=finished_at, summary=summary, error=error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id


def _finish_run(db: Session, run_id: str, status: str, summary=None, error=None) -> None:
    run = db.query(OperationRun).filter_by(id=run_id).first()
    if not run:
        return
    run.status = status
    run.finished_at = _dt()
    run.summary = summary
    run.error = error
    db.commit()


def recent_runs(db: Session, limit: int = 20) -> List[Dict]:
    rows = (
        db.query(OperationRun)
        .order_by(OperationRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "operation": r.operation,
            "origin": r.origin,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "summary": r.summary,
            "error": r.error,
        }
        for r in rows
    ]


# ── Trigger ───────────────────────────────────────────────────────

def trigger(op_name: str, origin: str = "manual", user_id: Optional[str] = None,
            params: Optional[Dict] = None) -> Dict:
    """Start an operation in the background. Guards against concurrent runs."""
    op = OPERATIONS.get(op_name)
    if not op:
        return {"started": False, "reason": f"Operación desconocida: {op_name}"}
    params = params or {}
    missing = [p for p in op.needs_params if not params.get(p)]
    if missing:
        return {"started": False, "reason": f"Faltan parámetros: {', '.join(missing)}"}

    with _lock:
        db = SessionLocal()
        try:
            if get_status(db, op_name).get("is_running"):
                return {"started": False, "reason": "Esta operación ya está en curso."}
            started_at = datetime.now(timezone.utc)
            write_status(db, op_name, is_running=True, phase="iniciando",
                         started_at=started_at.isoformat(), error=None)
            run_id = _record_run(db, op_name, origin, user_id, "running",
                                 started_at.replace(tzinfo=None))
        finally:
            db.close()

    def _worker():
        db2 = SessionLocal()
        try:
            def set_phase(msg: str) -> None:
                write_status(db2, op_name, is_running=True, phase=msg)
            result = op.runner(params, user_id, set_phase)
            if isinstance(result, dict) and result.get("error"):
                write_status(db2, op_name, is_running=False, phase="error",
                             last_result=result, error=result["error"])
                _finish_run(db2, run_id, "error", summary=result, error=result["error"])
            else:
                write_status(db2, op_name, is_running=False, phase="completado",
                             last_run=_now(), last_result=result, error=None)
                _finish_run(db2, run_id, "completed", summary=result)
        except Exception as e:  # noqa: BLE001 — report into status + history
            logger.exception("Operación %s falló", op_name)
            msg = str(e)
            write_status(db2, op_name, is_running=False, phase="error", error=msg)
            _finish_run(db2, run_id, "error", error=msg)
        finally:
            db2.close()

    _spawn(_worker)
    return {"started": True, "operation": op_name, "run_id": run_id}


def all_status(db: Session) -> Dict:
    """Live status of every console operation + schedule + recent history."""
    schedules = get_schedules(db)
    return {
        "operations": [
            {
                "name": op.name,
                "label": op.label,
                "description": op.description,
                "needs_params": op.needs_params,
                "status": get_status(db, op.name),
                "schedule": schedules.get(op.name),
            }
            for op in OPERATIONS.values()
        ],
        "history": recent_runs(db),
    }


# ── Scheduler (in-app, DB-driven — survives restarts) ─────────────
# A lightweight tick checks the durable schedule every minute and triggers due
# operations. No separate worker: the next-run lives in the DB, so a restart just
# resumes. Single web replica (railway numReplicas=1) → no double-fire.

import time  # noqa: E402
from datetime import timedelta  # noqa: E402
from modules.banking_score.models.models import OperationSchedule  # noqa: E402

_scheduler_started = False
SCHEDULER_TICK_SECONDS = 60


def get_schedules(db: Session) -> Dict[str, Dict]:
    try:
        rows = {r.operation: r for r in db.query(OperationSchedule).all()}
    except Exception:  # noqa: BLE001 — table may not exist yet (pre-migration/tests)
        db.rollback()
        rows = {}
    out = {}
    for name, op in OPERATIONS.items():
        r = rows.get(name)
        out[name] = {
            "operation": name,
            "enabled": bool(r.enabled) if r else False,
            "interval_hours": r.interval_hours if r else op.default_interval_hours,
            "params": (r.params if r else None) or {},
            "next_run_at": r.next_run_at.isoformat() if r and r.next_run_at else None,
            "last_run_at": r.last_run_at.isoformat() if r and r.last_run_at else None,
        }
    return out


def set_schedule(db: Session, op_name: str, enabled: bool,
                 interval_hours: Optional[int] = None, params: Optional[Dict] = None) -> Dict:
    if op_name not in OPERATIONS:
        raise ValueError(f"Operación desconocida: {op_name}")
    r = db.query(OperationSchedule).filter_by(operation=op_name).first()
    if not r:
        r = OperationSchedule(operation=op_name, enabled=False,
                              interval_hours=OPERATIONS[op_name].default_interval_hours)
        db.add(r)
    r.enabled = bool(enabled)
    if interval_hours is not None:
        r.interval_hours = max(1, int(interval_hours))
    if params is not None:
        r.params = params
    r.next_run_at = (_dt() + timedelta(hours=r.interval_hours)) if r.enabled else None
    db.commit()
    return get_schedules(db)[op_name]


def run_due_schedules(db: Optional[Session] = None) -> int:
    """Trigger every enabled schedule whose next_run_at has passed. Returns count.

    Firing uses an atomic claim (UPDATE … WHERE next_run_at <= now) so that with
    multiple uvicorn workers each running a tick, only the worker whose UPDATE
    matches the still-due row fires it — no double-run.
    """
    own = db is None
    db = db or SessionLocal()
    try:
        now = _dt()
        try:
            due = (
                db.query(OperationSchedule)
                .filter(OperationSchedule.enabled.is_(True))
                .filter(OperationSchedule.next_run_at.isnot(None))
                .filter(OperationSchedule.next_run_at <= now)
                .all()
            )
        except Exception:  # noqa: BLE001 — table missing (pre-migration)
            db.rollback()
            return 0
        fired = 0
        for sched in due:
            op_name = sched.operation
            interval = sched.interval_hours
            params = sched.params or {}
            # Atomic claim: advance next_run_at only if it's still due. The loser
            # gets rowcount 0 (the row no longer matches) and skips.
            claimed = db.execute(
                update(OperationSchedule)
                .where(OperationSchedule.operation == op_name)
                .where(OperationSchedule.next_run_at <= now)
                .values(next_run_at=now + timedelta(hours=interval), last_run_at=now)
            ).rowcount
            db.commit()
            if claimed != 1:
                continue  # another worker claimed this slot
            if op_name not in OPERATIONS:
                continue
            if get_status(db, op_name).get("is_running"):
                continue  # let the running one finish; re-check next interval
            if trigger(op_name, origin="schedule", user_id=None, params=params).get("started"):
                fired += 1
        return fired
    finally:
        if own:
            db.close()


def start_scheduler() -> None:
    """Start the in-process scheduler tick once (idempotent)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        while True:
            try:
                run_due_schedules()
            except Exception:  # noqa: BLE001 — a tick failure must not kill the loop
                logger.exception("scheduler tick failed")
            time.sleep(SCHEDULER_TICK_SECONDS)

    threading.Thread(target=_loop, daemon=True).start()
    logger.info("Operation scheduler started (tick=%ss)", SCHEDULER_TICK_SECONDS)
