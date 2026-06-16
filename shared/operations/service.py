"""Operation console — generic framework (status + history + scheduler).

Platform infra: any module registers its recurring operations via
:func:`register_operation`, and they become triggerable, monitorable and
schedulable from the UI through one console. No module-to-module imports — each
module owns its runners and registers them at import time.

- Live status: shared across workers (AppSetting KV ``op_status:{name}``), with a
  heartbeat to detect hung runs. Each operation runs in a daemon thread.
- History: every run writes an ``operation_runs`` row (origin, user, start/end,
  result), for audit.
- Scheduler: a durable cadence (``operation_schedules``) checked by an in-process
  tick; the next-run lives in the DB, so it survives restarts. Firing uses an
  atomic claim so multiple uvicorn workers don't double-fire.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
from shared.operations.models import OperationRun, OperationSchedule

logger = logging.getLogger("sdq.operations")

_STALE_SECONDS = 30 * 60
SCHEDULER_TICK_SECONDS = 60
_lock = threading.Lock()
_scheduler_started = False

_DEFAULT_STATUS: Dict = {
    "is_running": False, "phase": "", "started_at": None, "last_run": None,
    "last_result": None, "error": None, "heartbeat": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt():
    """Naive UTC for DateTime columns (Postgres TIMESTAMP WITHOUT TZ + SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(op: str) -> str:
    return f"op_status:{op}"


def _spawn(target: Callable[[], None]) -> None:
    """Run *target* in a daemon thread. Indirection so tests run synchronously."""
    threading.Thread(target=target, daemon=True).start()


# ── Registry ──────────────────────────────────────────────────────

class Operation:
    def __init__(self, name: str, label: str, description: str, runner: Callable,
                 default_interval_hours: int, needs_params: Optional[List[str]] = None):
        self.name = name
        self.label = label
        self.description = description
        self.runner = runner
        self.default_interval_hours = default_interval_hours
        self.needs_params = needs_params or []


OPERATIONS: Dict[str, Operation] = {}


def register_operation(op: Operation) -> Operation:
    """Register a console operation. Modules call this at import time."""
    OPERATIONS[op.name] = op
    return op


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
    rows = db.query(OperationRun).order_by(OperationRun.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "operation": r.operation, "origin": r.origin, "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "summary": r.summary, "error": r.error,
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
                "name": op.name, "label": op.label, "description": op.description,
                "needs_params": op.needs_params, "status": get_status(db, op.name),
                "schedule": schedules.get(op.name),
            }
            for op in OPERATIONS.values()
        ],
        "history": recent_runs(db),
    }


# ── Scheduler (in-app, DB-driven — survives restarts) ─────────────

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

    _spawn(_loop)
    logger.info("Operation scheduler started (tick=%ss)", SCHEDULER_TICK_SECONDS)
