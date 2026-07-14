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
                 default_interval_hours: int, needs_params: Optional[List[str]] = None,
                 triggers: Optional[List[str]] = None):
        self.name = name
        self.label = label
        self.description = description
        self.runner = runner
        self.default_interval_hours = default_interval_hours
        self.needs_params = needs_params or []
        # Operaciones a DISPARAR cuando esta termina con éxito (cascada por dependencia):
        # el dato nuevo fluye solo aguas abajo (re-score → re-valida) sin intervención
        # manual. El grafo debe ser ACÍCLICO; el guard de "ya en curso" deduplica disparos
        # concurrentes (varias fuentes que alimentan el mismo re-score).
        self.triggers = list(triggers or [])


OPERATIONS: Dict[str, Operation] = {}


def is_on_demand(op: Operation) -> bool:
    """Una operación es BAJO DEMANDA (no admite agenda automática) si no tiene una cadencia
    natural (``default_interval_hours <= 0``) o si necesita parámetros para correr (p.ej. un
    ``period``): agendarla no tiene sentido — o correría sin el parámetro, o repetiría un
    trabajo puntual (backfills de historia, backtests, purgas, sondeos read-only)."""
    return op.default_interval_hours <= 0 or bool(op.needs_params)


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


def clear_orphaned_runs(db: Session) -> int:
    """Al ARRANCAR el proceso, toda op con ``is_running=True`` quedó HUÉRFANA: su hilo murió
    con el proceso anterior (p. ej. un deploy la cortó a media corrida). El flag stale bloquea
    (guard "ya en curso") que un nuevo disparo la re-arranque hasta que expire (``_STALE_SECONDS``,
    30 min) — una op LARGA (como ``prewarm-report-cache``) cortada por un deploy quedaría muerta
    y sin poder reintentar en ese lapso. Esto lo limpia de una: marca esas ops como no-corriendo
    y cierra sus filas ``OperationRun`` 'running'. Idempotente; best-effort (nunca rompe el boot)."""
    cleared = 0
    for name in list(OPERATIONS):
        st = _read_status(db, name)
        if st.get("is_running"):
            write_status(db, name, is_running=False, phase="(interrumpido por reinicio)")
            cleared += 1
    try:
        db.query(OperationRun).filter(OperationRun.status == "running").update(
            {OperationRun.status: "interrupted"}, synchronize_session=False)
        db.commit()
    except Exception:  # noqa: BLE001 — best-effort; el status ya quedó limpio
        db.rollback()
    if cleared:
        logger.info("Ops huérfanas limpiadas al arranque: %d", cleared)
    return cleared


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

def _fire_cascade(op_name: str) -> None:
    """Dispara las operaciones aguas abajo declaradas por *op_name* tras un éxito.

    El lazo de auto-mejora: una fuente que termina re-puntúa y re-valida sola, sin que
    un humano dispare la cadena. ``origin="cascade"`` la distingue en el historial. Un
    fallo al encadenar no debe romper la corrida que ya terminó bien (aislado)."""
    op = OPERATIONS.get(op_name)
    if not op or not op.triggers:
        return
    for dep in op.triggers:
        try:
            res = trigger(dep, origin="cascade", user_id=None)
            if not res.get("started"):
                logger.info("cascada %s→%s no disparó: %s", op_name, dep, res.get("reason"))
        except Exception:  # noqa: BLE001 — una cascada fallida no rompe el éxito previo
            logger.exception("cascada %s→%s falló", op_name, dep)


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
                _fire_cascade(op_name)
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
                "needs_params": op.needs_params, "on_demand": is_on_demand(op),
                "status": get_status(db, op.name), "schedule": schedules.get(op.name),
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
    # Las operaciones bajo demanda no se agendan: encenderlas forzaría una cadencia mínima de
    # 1h (``max(1, 0)``) sobre trabajos puntuales/costosos (backfills, backtests, purgas). Se
    # rechaza en el backend además de ocultarse en la UI (defensa en profundidad).
    if enabled and is_on_demand(OPERATIONS[op_name]):
        raise ValueError(
            f"«{OPERATIONS[op_name].label}» es una operación bajo demanda: se ejecuta a mano, "
            "no admite agenda automática.")
    try:
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
    except Exception:  # noqa: BLE001 — rastro para diagnóstico + sesión limpia; el error
        # real sube (500), señal correcta para monitoreo. La UI lo muestra igual (el toggle
        # es optimista y revierte mostrando el error).
        db.rollback()
        logger.exception("set_schedule falló para %s", op_name)
        raise


def seed_default_schedules(db: Optional[Session] = None) -> int:
    """Activa una agenda por defecto para cada operación recurrente que aún no tenga una.

    Idempotente: solo CREA las que faltan (respeta lo que el admin haya configurado a
    mano después), activadas con la cadencia recomendada de cada operación. Omite las
    on-demand (cadencia 0) y las que necesitan parámetros. Devuelve cuántas creó.

    Permite que un deploy nuevo corra todas las syncs solo, sin togglear a mano. Seguro
    con múltiples workers: el INSERT compite por la unique constraint y el perdedor
    revierte sin duplicar.
    """
    own = db is None
    db = db or SessionLocal()
    try:
        try:
            existing = {r.operation for r in db.query(OperationSchedule).all()}
        except Exception:  # noqa: BLE001 — tabla ausente (pre-migración/tests)
            db.rollback()
            return 0
        created = 0
        idx = 0
        for name, op in OPERATIONS.items():
            if name in existing or op.default_interval_hours <= 0 or op.needs_params:
                continue
            # Escalonar los PRIMEROS disparos a los pocos minutos del arranque (no a una
            # cadencia entera: una fuente anual no debe esperar un año para su 1ª corrida).
            # Así los datos viejos se ponen al día pronto, sin avalancha (3 min entre cada
            # una). De ahí en más cada operación sigue su cadencia normal.
            idx += 1
            db.add(OperationSchedule(
                operation=name, enabled=True, interval_hours=op.default_interval_hours,
                next_run_at=_dt() + timedelta(minutes=3 * idx)))
            try:
                db.commit()
                created += 1
            except Exception:  # noqa: BLE001 — otro worker tomó el slot (unique)
                db.rollback()
        if created:
            logger.info("seed_default_schedules: %d agendas creadas", created)
        return created
    finally:
        if own:
            db.close()


def normalize_ondemand_schedules(db: Optional[Session] = None) -> int:
    """Apaga cualquier agenda ACTIVA de una operación BAJO DEMANDA. Autocorrección idempotente.

    Cierra el borde áspero por el que activar una operación bajo demanda (cadencia 0) la dejaba
    corriendo cada 1h (``max(1, 0)``): un backfill de historia o un backtest agendado repite
    trabajo costoso sin sentido. Corre en el arranque, tras ``seed_default_schedules``, así un
    deploy limpia solo los toggles accidentales. Devuelve cuántas apagó."""
    own = db is None
    db = db or SessionLocal()
    try:
        try:
            rows = db.query(OperationSchedule).filter_by(enabled=True).all()
        except Exception:  # noqa: BLE001 — tabla ausente (pre-migración/tests)
            db.rollback()
            return 0
        to_disable = [
            str(r.operation) for r in rows
            if (op := OPERATIONS.get(str(r.operation))) is not None and is_on_demand(op)
        ]
        if not to_disable:
            return 0
        db.query(OperationSchedule).filter(
            OperationSchedule.operation.in_(to_disable)).update(
            {"enabled": False, "next_run_at": None}, synchronize_session=False)
        db.commit()
        logger.info("normalize_ondemand_schedules: %d agendas bajo-demanda apagadas",
                    len(to_disable))
        return len(to_disable)
    finally:
        if own:
            db.close()


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
