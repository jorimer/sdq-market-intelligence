"""Tests for the Operation Console layer (status + history + trigger)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
import shared.auth.models  # noqa: F401 — register users (FK target)
import shared.settings.models  # noqa: F401 — register app_setting
import shared.operations.models  # noqa: F401 — register operation_runs/schedules
import modules.banking_score.operations  # noqa: F401 — registers banking ops (rescore, recompute…)
from shared.operations import service as operations


@pytest.fixture()
def Session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SL = sessionmaker(bind=engine)
    monkeypatch.setattr(operations, "SessionLocal", SL)
    # Run the worker synchronously so completion is deterministic.
    monkeypatch.setattr(operations, "_spawn", lambda target: target())
    return SL


def test_trigger_runs_and_records_history(Session):
    def runner(params, user_id, set_phase):
        set_phase("trabajando")
        return {"ok": True, "echo": params.get("x")}

    operations.OPERATIONS["_test_op"] = operations.Operation(
        "_test_op", "Test", "desc", runner, default_interval_hours=0)
    try:
        res = operations.trigger("_test_op", origin="manual", user_id=None, params={"x": 42})
        assert res["started"] is True

        db = Session()
        st = operations.get_status(db, "_test_op")
        assert st["is_running"] is False
        assert st["phase"] == "completado"
        assert st["last_result"]["echo"] == 42

        runs = [r for r in operations.recent_runs(db) if r["operation"] == "_test_op"]
        db.close()
        assert runs and runs[0]["status"] == "completed"
        assert runs[0]["finished_at"] is not None
    finally:
        operations.OPERATIONS.pop("_test_op", None)


def test_error_runner_records_error(Session):
    def boom(params, user_id, set_phase):
        raise RuntimeError("kaboom")

    operations.OPERATIONS["_boom"] = operations.Operation(
        "_boom", "Boom", "desc", boom, default_interval_hours=0)
    try:
        operations.trigger("_boom")
        db = Session()
        st = operations.get_status(db, "_boom")
        assert st["phase"] == "error"
        assert "kaboom" in (st["error"] or "")
        runs = [r for r in operations.recent_runs(db) if r["operation"] == "_boom"]
        db.close()
        assert runs and runs[0]["status"] == "error"
    finally:
        operations.OPERATIONS.pop("_boom", None)


def test_trigger_guards_concurrent_run(Session):
    db = Session()
    operations.write_status(db, "rescore", is_running=True, phase="x", started_at=operations._now())
    db.close()
    res = operations.trigger("rescore")
    assert res["started"] is False
    assert "curso" in res["reason"]


def test_trigger_missing_required_param(Session):
    res = operations.trigger("recompute-carteras", params={})
    assert res["started"] is False
    assert "period" in res["reason"]


def test_unknown_operation(Session):
    res = operations.trigger("no-such-op")
    assert res["started"] is False


def test_all_status_shape(Session):
    db = Session()
    data = operations.all_status(db)
    db.close()
    names = {o["name"] for o in data["operations"]}
    assert {"rescore", "prune-future", "recompute-carteras"} <= names
    assert "history" in data
    assert all("schedule" in o for o in data["operations"])


def test_set_schedule_enables_and_sets_next_run(Session):
    db = Session()
    sch = operations.set_schedule(db, "rescore", enabled=True, interval_hours=24)
    db.close()
    assert sch["enabled"] is True
    assert sch["interval_hours"] == 24
    assert sch["next_run_at"] is not None


def test_set_schedule_disable_clears_next_run(Session):
    db = Session()
    operations.set_schedule(db, "rescore", enabled=True, interval_hours=24)
    sch = operations.set_schedule(db, "rescore", enabled=False)
    db.close()
    assert sch["enabled"] is False
    assert sch["next_run_at"] is None


def test_run_due_schedules_fires_due_and_advances(Session):
    from datetime import timedelta
    from shared.operations.models import OperationSchedule

    fired_ops = []

    def runner(params, user_id, set_phase):
        fired_ops.append(params.get("tag"))
        return {"ok": True}

    operations.OPERATIONS["_sched_op"] = operations.Operation(
        "_sched_op", "Sched", "desc", runner, default_interval_hours=24)
    try:
        db = Session()
        # Due in the past → should fire.
        db.add(OperationSchedule(
            operation="_sched_op", enabled=True, interval_hours=24,
            params={"tag": "x"}, next_run_at=operations._dt() - timedelta(hours=1)))
        db.commit()
        db.close()

        n = operations.run_due_schedules()
        assert n == 1
        assert fired_ops == ["x"]

        # next_run_at advanced into the future → second tick fires nothing.
        assert operations.run_due_schedules() == 0
    finally:
        operations.OPERATIONS.pop("_sched_op", None)


def test_run_due_skips_not_yet_due(Session):
    from datetime import timedelta
    from shared.operations.models import OperationSchedule
    db = Session()
    db.add(OperationSchedule(
        operation="rescore", enabled=True, interval_hours=24,
        next_run_at=operations._dt() + timedelta(hours=5)))
    db.commit()
    db.close()
    assert operations.run_due_schedules() == 0
