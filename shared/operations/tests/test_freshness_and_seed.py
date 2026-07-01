"""Tests del auto-agendado (seed) y la auditoría de frescura de datos."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User, UserRole
from shared.notifications.service import Notification, notification_service
from shared.operations.models import OperationRun, OperationSchedule
from shared.operations.service import (
    OPERATIONS,
    Operation,
    register_operation,
    seed_default_schedules,
)
from shared.operations import freshness as fr
from shared.settings.models import AppSetting


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        OperationSchedule.__table__, OperationRun.__table__, AppSetting.__table__,
        User.__table__, Notification.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def temp_ops():
    """Aísla el registro a SOLO las operaciones de prueba (limpia el dict global y lo
    restaura al terminar), para que la auditoría no vea las ~30 ops reales registradas
    por otros tests del suite. ``freshness`` y ``service`` comparten el mismo dict."""
    saved = dict(OPERATIONS)
    OPERATIONS.clear()
    register_operation(Operation("t-recurring", "Recurrente", "d", lambda *a: {}, 24))
    register_operation(Operation("t-ondemand", "On-demand", "d", lambda *a: {}, 0))
    register_operation(Operation("t-needsparam", "Param", "d", lambda *a: {}, 24,
                                 needs_params=["period"]))
    try:
        yield ["t-recurring", "t-ondemand", "t-needsparam"]
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(saved)


def _naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _admin(db, email="a@x.com", role=UserRole.admin):
    u = User(email=email, password_hash="x", full_name="A", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


# ── seed ──────────────────────────────────────────────────────────

def test_seed_enables_recurring_skips_ondemand_and_param(db, temp_ops):
    created = seed_default_schedules(db)
    rows = {r.operation: r for r in db.query(OperationSchedule).all()}
    assert "t-recurring" in rows and rows["t-recurring"].enabled is True
    assert rows["t-recurring"].interval_hours == 24
    assert rows["t-recurring"].next_run_at is not None
    assert "t-ondemand" not in rows       # cadencia 0 → on-demand
    assert "t-needsparam" not in rows     # necesita parámetros
    assert created >= 1


def test_seed_is_idempotent_and_respects_manual(db, temp_ops):
    seed_default_schedules(db)
    # apagar manualmente
    r = db.query(OperationSchedule).filter_by(operation="t-recurring").first()
    r.enabled = False
    db.commit()
    created2 = seed_default_schedules(db)
    assert created2 == 0  # no recrea las existentes
    r2 = db.query(OperationSchedule).filter_by(operation="t-recurring").first()
    assert r2.enabled is False  # respeta el apagado manual


# ── auditoría de frescura ─────────────────────────────────────────

def test_audit_flags_never_run_and_notifies_admins(db, temp_ops):
    _admin(db, "admin@x.com", UserRole.admin)
    _admin(db, "super@x.com", UserRole.super_admin)
    _admin(db, "viewer@x.com", UserRole.viewer)  # NO debe recibir
    res = fr.run_freshness_audit(db)
    assert "t-recurring" in res["overdue"]      # nunca corrió → atrasada
    assert res["notified"] >= 1
    # dos admins notificados, el viewer no
    assert db.query(Notification).filter_by(user_id=_uid(db, "admin@x.com")).count() == 1
    assert db.query(Notification).filter_by(user_id=_uid(db, "super@x.com")).count() == 1
    assert db.query(Notification).filter_by(user_id=_uid(db, "viewer@x.com")).count() == 0


def test_audit_recent_success_is_fresh(db, temp_ops):
    _admin(db)
    db.add(OperationRun(operation="t-recurring", origin="schedule", status="completed",
                        started_at=_naive_now(), finished_at=_naive_now()))
    db.commit()
    res = fr.run_freshness_audit(db)
    assert "t-recurring" not in res["overdue"]
    assert db.query(Notification).count() == 0


def test_audit_old_success_is_overdue(db, temp_ops):
    _admin(db)
    old = _naive_now() - timedelta(hours=24 * 3)  # 3 días, cadencia 24h → atrasado
    db.add(OperationRun(operation="t-recurring", origin="schedule", status="completed",
                        started_at=old, finished_at=old))
    db.commit()
    res = fr.run_freshness_audit(db)
    assert "t-recurring" in res["overdue"]


def test_audit_dedups_then_renotifies_after_recovery(db, temp_ops):
    _admin(db)
    fr.run_freshness_audit(db)                     # 1er aviso (nunca corrió)
    n1 = db.query(Notification).count()
    fr.run_freshness_audit(db)                     # dedup: no repite
    assert db.query(Notification).count() == n1
    # la fuente se pone al día → marcador limpiado
    db.add(OperationRun(operation="t-recurring", origin="schedule", status="completed",
                        started_at=_naive_now(), finished_at=_naive_now()))
    db.commit()
    fr.run_freshness_audit(db)                     # fresca → sin aviso, limpia marcador
    assert db.query(AppSetting).filter_by(key=fr._alert_key("t-recurring")).count() == 0


def _uid(db, email):
    return db.query(User).filter_by(email=email).first().id


def test_sovereign_audit_proposes_old_action(db, temp_ops):
    """La auditoría PROPONE re-verificar un rating soberano cuya última acción envejeció.
    El store no tiene OperationRun; su frescura se mide por el action_date del dato."""
    from datetime import date
    from shared.contracts.sovereign_ratings import save_sovereign_ratings

    _admin(db)
    save_sovereign_ratings(db, {
        "DO": {"sp": {"rating": "BB", "action_date": "2022-12-19"}},  # ~viejo
        "CR": {"sp": {"rating": "BB", "action_date": "2026-05-01"}},  # fresco
    })
    proposed = fr._audit_sovereign_ratings(db, [_uid(db, "a@x.com")],
                                           datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert proposed == ["DO"]
    notes = db.query(Notification).all()
    assert len(notes) == 1 and "DO" in notes[0].title
    # dedup: segunda corrida no repite el aviso.
    again = fr._audit_sovereign_ratings(db, [_uid(db, "a@x.com")],
                                        datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert again == []
    assert db.query(Notification).count() == 1
