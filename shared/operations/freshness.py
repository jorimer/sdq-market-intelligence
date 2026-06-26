"""Auditoría de frescura de datos — alerta de "dato viejo".

Operación de consola (agendable, diaria): para cada fuente recurrente compara su
última sincronización EXITOSA contra su cadencia; si se pasó (con margen), o nunca
corrió, notifica a los administradores (buzón in-app). Deduplica para no repetir el
mismo aviso a diario: re-notifica solo si pasó otra cadencia o si la fuente se puso
al día y volvió a atrasarse.

Cross-módulo por diseño (revisa TODAS las operaciones del registro); vive en el
framework de operaciones, no en un módulo de sector.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from shared.auth.models import User, UserRole
from shared.database.session import SessionLocal
from shared.notifications.service import notification_service
from shared.operations.models import OperationRun
from shared.operations.service import (
    OPERATIONS,
    Operation,
    get_schedules,
    register_operation,
)
from shared.settings.models import AppSetting

logger = logging.getLogger("sdq.operations.freshness")

FRESHNESS_OP_NAME = "data-freshness-audit"
# Margen sobre la cadencia antes de marcar "viejo" (evita falsos positivos por un
# pequeño retraso de publicación de la fuente).
_GRACE = 1.5


def _now_naive() -> datetime:
    """UTC naive (las columnas DateTime son naive: Postgres TIMESTAMP s/ TZ + SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alert_key(op: str) -> str:
    return f"freshness_alert:{op}"


def _last_success(db: Session, op_name: str) -> Optional[datetime]:
    """Fin de la última corrida EXITOSA de *op_name*, o None si nunca completó."""
    row = (
        db.query(OperationRun)
        .filter(OperationRun.operation == op_name, OperationRun.status == "completed")
        .order_by(OperationRun.finished_at.desc().nullslast())
        .first()
    )
    return row.finished_at if row else None


def _recently_notified(db: Session, op_name: str, interval_hours: int) -> bool:
    """¿Ya se avisó por esta fuente dentro de su última cadencia? (anti-spam)."""
    row = db.query(AppSetting).filter(AppSetting.key == _alert_key(op_name)).first()
    if not row or not row.value:
        return False
    try:
        last = datetime.fromisoformat(row.value)
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - last).total_seconds() < interval_hours * 3600


def _mark_notified(db: Session, op_name: str) -> None:
    key = _alert_key(op_name)
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = datetime.now(timezone.utc).isoformat()
        row.is_secret = False
    else:
        db.add(AppSetting(key=key, value=datetime.now(timezone.utc).isoformat(), is_secret=False))
    db.commit()


def _clear_notified(db: Session, op_name: str) -> None:
    """La fuente volvió a estar al día → limpiar el marcador para re-avisar si recae."""
    row = db.query(AppSetting).filter(AppSetting.key == _alert_key(op_name)).first()
    if row:
        db.delete(row)
        db.commit()


def _admin_ids(db: Session) -> List[str]:
    """IDs de usuarios activos con rol admin o super_admin (destinatarios de la alerta)."""
    rows = (
        db.query(User)
        .filter(User.is_active.is_(True),
                User.role.in_([UserRole.admin, UserRole.super_admin]))
        .all()
    )
    return [u.id for u in rows]


def run_freshness_audit(db: Session) -> Dict:
    """Audita la frescura de cada fuente recurrente y notifica las atrasadas.

    Devuelve ``{checked, n_overdue, overdue, notified}``. Solo considera operaciones
    con cadencia (>0) que no necesitan parámetros (las on-demand no tienen frescura
    esperada). No se audita a sí misma.
    """
    scheds = get_schedules(db)
    admin_ids = _admin_ids(db)
    now = _now_naive()
    checked = 0
    overdue: List[str] = []
    notified = 0

    for name, op in OPERATIONS.items():
        if name == FRESHNESS_OP_NAME:
            continue
        if op.default_interval_hours <= 0 or op.needs_params:
            continue  # on-demand / parametrizada → sin frescura esperada
        sched = scheds.get(name) or {}
        interval = sched.get("interval_hours") or op.default_interval_hours
        checked += 1

        last = _last_success(db, name)
        if last is not None:
            elapsed_h = (now - last).total_seconds() / 3600
            is_overdue = elapsed_h > interval * _GRACE
        else:
            elapsed_h = None
            is_overdue = True  # nunca sincronizó

        if not is_overdue:
            _clear_notified(db, name)
            continue

        overdue.append(name)
        if _recently_notified(db, name, interval):
            continue

        title = f"Dato desactualizado: {op.label}"
        if elapsed_h is None:
            body = (f"La fuente «{op.label}» nunca se sincronizó con éxito. "
                    f"Cadencia esperada: cada {interval} h.")
        else:
            days = int(elapsed_h // 24)
            body = (f"«{op.label}» no se actualiza hace ~{days} día(s) "
                    f"(cadencia esperada: cada {interval} h).")
        for uid in admin_ids:
            notification_service.create(db, user_id=uid, type="warning", title=title, body=body)
        _mark_notified(db, name)
        notified += 1

    return {"checked": checked, "n_overdue": len(overdue),
            "overdue": overdue, "notified": notified}


def _run(params, user_id, set_phase) -> Dict:
    db = SessionLocal()
    try:
        set_phase("auditando frescura de las fuentes de datos")
        return run_freshness_audit(db)
    finally:
        db.close()


register_operation(Operation(
    name=FRESHNESS_OP_NAME,
    label="Auditoría de frescura de datos",
    description="Revisa cada fuente: si su última sincronización exitosa se pasó de su "
                "cadencia (o nunca corrió), notifica a los administradores. Agendable "
                "(recomendada diaria).",
    runner=_run,
    default_interval_hours=24,
))
