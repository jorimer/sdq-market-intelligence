"""Al arrancar el proceso, `clear_orphaned_runs` limpia las ops con `is_running` huérfano
(un deploy cortó una corrida larga) para que un nuevo disparo no quede bloqueado 30 min por
el guard de "ya en curso"."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.operations.service as svc
from shared.database.base import Base
from shared.operations.models import OperationRun  # noqa: F401 — registra la tabla
from shared.operations.service import (
    OPERATIONS,
    Operation,
    clear_orphaned_runs,
    register_operation,
    write_status,
)
from shared.settings.models import AppSetting  # noqa: F401 — registra la tabla


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__, OperationRun.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def temp_ops():
    saved = dict(OPERATIONS)
    OPERATIONS.clear()
    try:
        yield
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(saved)


def test_clears_running_flag(db, temp_ops):
    register_operation(Operation("longop", "Long", "d", lambda *a: {}, 24))
    write_status(db, "longop", is_running=True, phase="a mitad")
    assert clear_orphaned_runs(db) == 1
    st = svc._read_status(db, "longop")
    assert st["is_running"] is False
    assert "reinicio" in (st.get("phase") or "")


def test_noop_when_idle(db, temp_ops):
    register_operation(Operation("idle", "Idle", "d", lambda *a: {}, 24))
    write_status(db, "idle", is_running=False, phase="completado")
    assert clear_orphaned_runs(db) == 0


def test_marks_running_operation_runs_interrupted(db, temp_ops):
    register_operation(Operation("op", "Op", "d", lambda *a: {}, 24))
    db.add(OperationRun(operation="op", origin="schedule", status="running"))
    db.add(OperationRun(operation="op", origin="manual", status="completed"))
    db.commit()
    clear_orphaned_runs(db)
    statuses = sorted(r.status for r in db.query(OperationRun).all())
    assert statuses == ["completed", "interrupted"]
