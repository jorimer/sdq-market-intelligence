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
    all_status,
    is_on_demand,
    normalize_ondemand_schedules,
    register_operation,
    seed_default_schedules,
    set_schedule,
)
from shared.operations import freshness as fr
from shared.publications.models import Publication
from shared.settings.models import AppSetting


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        OperationSchedule.__table__, OperationRun.__table__, AppSetting.__table__,
        User.__table__, Notification.__table__, Publication.__table__,
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


# ── bajo demanda: clasificación, guard y autocorrección ───────────

def test_is_on_demand_classification(temp_ops):
    assert is_on_demand(OPERATIONS["t-ondemand"]) is True     # cadencia 0
    assert is_on_demand(OPERATIONS["t-needsparam"]) is True   # necesita parámetros
    assert is_on_demand(OPERATIONS["t-recurring"]) is False


def test_set_schedule_rejects_enabling_ondemand(db, temp_ops):
    with pytest.raises(ValueError, match="bajo demanda"):
        set_schedule(db, "t-ondemand", enabled=True)
    with pytest.raises(ValueError, match="bajo demanda"):
        set_schedule(db, "t-needsparam", enabled=True, interval_hours=24)
    # una recurrente sí se puede agendar
    out = set_schedule(db, "t-recurring", enabled=True, interval_hours=24)
    assert out["enabled"] is True


def test_normalize_disables_enabled_ondemand_only(db, temp_ops):
    # Simula el estado accidental: agendas activas para on-demand/param (como las que dejó el
    # borde áspero max(1,0)=1h) + una recurrente legítima.
    now = _naive_now()
    db.add_all([
        OperationSchedule(operation="t-ondemand", enabled=True, interval_hours=1,
                          next_run_at=now),
        OperationSchedule(operation="t-needsparam", enabled=True, interval_hours=24,
                          next_run_at=now),
        OperationSchedule(operation="t-recurring", enabled=True, interval_hours=24,
                          next_run_at=now),
    ])
    db.commit()
    fixed = normalize_ondemand_schedules(db)
    assert fixed == 2
    rows = {r.operation: r for r in db.query(OperationSchedule).all()}
    assert rows["t-ondemand"].enabled is False and rows["t-ondemand"].next_run_at is None
    assert rows["t-needsparam"].enabled is False
    assert rows["t-recurring"].enabled is True   # la recurrente no se toca
    # idempotente
    assert normalize_ondemand_schedules(db) == 0


def test_all_status_exposes_on_demand_flag(db, temp_ops):
    ops = {o["name"]: o for o in all_status(db)["operations"]}
    assert ops["t-ondemand"]["on_demand"] is True
    assert ops["t-needsparam"]["on_demand"] is True
    assert ops["t-recurring"]["on_demand"] is False


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
    assert db.query(AppSetting).filter_by(key=fr._DEDUP._key("t-recurring")).count() == 0


def _uid(db, email):
    return db.query(User).filter_by(email=email).first().id


# ── frescura de publicaciones BCRD (edición nueva que no aparece) ──

def _seed_pub(db, report_key, age_days, status="ok"):
    """Inserta una edición ingerida con created_at hace *age_days* días."""
    row = Publication(report_key=report_key, report_name=report_key, period=f"p{age_days}",
                      status=status, created_at=_naive_now() - timedelta(days=age_days))
    db.add(row)
    db.commit()
    return row


def test_publication_stale_alerts_admins(db):
    # IPOM es trimestral (90d); umbral = 90 * 1.5 = 135d. 200 días → atrasado.
    _admin(db, "admin@x.com", UserRole.admin)
    _admin(db, "viewer@x.com", UserRole.viewer)  # NO debe recibir
    _seed_pub(db, "politica_monetaria", age_days=200)
    alerted = fr._audit_publications(db, [_uid(db, "admin@x.com")], _naive_now())
    assert alerted == ["politica_monetaria"]
    assert db.query(Notification).filter_by(user_id=_uid(db, "admin@x.com")).count() == 1


def test_publication_fresh_no_alert(db):
    _admin(db)
    _seed_pub(db, "politica_monetaria", age_days=10)  # dentro de la cadencia trimestral
    alerted = fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())
    assert alerted == []
    assert db.query(Notification).count() == 0


def test_publication_never_ingested_is_not_alerted_here(db):
    # Sin filas ingeridas → lo cubre la frescura de la OPERACIÓN, no esta auditoría.
    _admin(db)
    alerted = fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())
    assert alerted == []
    assert db.query(Notification).count() == 0


def test_publication_errored_edition_does_not_count(db):
    # Una edición 'error' vieja no cuenta como ingestión exitosa → no hay 'ok' → no avisa.
    _admin(db)
    _seed_pub(db, "politica_monetaria", age_days=300, status="error")
    alerted = fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())
    assert alerted == []


def test_publication_dedups_then_clears_on_recovery(db):
    _admin(db)
    _seed_pub(db, "politica_monetaria", age_days=200)
    fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())  # 1er aviso
    n1 = db.query(Notification).count()
    assert n1 == 1
    fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())  # dedup
    assert db.query(Notification).count() == n1
    # aparece una edición nueva (fresca) → limpia el marcador para re-avisar si recae
    _seed_pub(db, "politica_monetaria", age_days=1)
    fr._audit_publications(db, [_uid(db, "a@x.com")], _naive_now())
    assert db.query(AppSetting).filter_by(key=fr._DEDUP._key("publication:politica_monetaria")).count() == 0


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
