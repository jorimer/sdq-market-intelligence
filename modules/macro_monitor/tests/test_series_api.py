"""Router tests for the admin DELETE /series/{series_code} maintenance endpoint."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from modules.macro_monitor.api.router import router
from modules.macro_monitor.models.models import MacroSeries


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed(db, series_code, period, value=1.0):
    db.add(MacroSeries(series_code=series_code, period=period, value=value))
    db.commit()


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/macro-monitor")

    class _U:
        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def test_delete_series_admin_removes_all_periods(db):
    _seed(db, "bcrd.sector_externo.cuentas_corrientes.2023", "2026-06")
    _seed(db, "bcrd.sector_externo.cuentas_corrientes.2023", "2026-05")
    _seed(db, "bcrd.sector_externo.cuentas_corrientes", "2025")  # survivor
    c = _client(db)

    r = c.delete("/api/v1/macro-monitor/series/bcrd.sector_externo.cuentas_corrientes.2023")

    assert r.status_code == 200
    assert r.json() == {
        "series_code": "bcrd.sector_externo.cuentas_corrientes.2023",
        "deleted": 2,
    }
    remaining = {row.series_code for row in db.query(MacroSeries).all()}
    assert remaining == {"bcrd.sector_externo.cuentas_corrientes"}


def test_delete_series_absent_code_is_noop(db):
    c = _client(db)
    r = c.delete("/api/v1/macro-monitor/series/no.such.code")
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


def test_delete_series_requires_admin(db):
    _seed(db, "bcrd.sector_externo.cuentas_corrientes.2023", "2026-06")
    c = _client(db, role=UserRole.viewer)
    r = c.delete("/api/v1/macro-monitor/series/bcrd.sector_externo.cuentas_corrientes.2023")
    assert r.status_code == 403
    # row untouched
    assert db.query(MacroSeries).count() == 1


# ─── AI insight (with_ai) — gated, best-effort ──────────────────

def test_series_with_ai_false_has_no_insight(db):
    _seed(db, "bcrd.test.serie", "2026-01", 1.0)
    _seed(db, "bcrd.test.serie", "2026-02", 2.0)
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/series/bcrd.test.serie", params={"with_ai": "false"})
    assert r.status_code == 200
    body = r.json()
    assert "ai_insight" in body
    assert body["ai_insight"] is None  # deterministic, fast


def test_series_with_ai_true_best_effort(db):
    _seed(db, "bcrd.test.serie", "2026-01", 1.0)
    _seed(db, "bcrd.test.serie", "2026-02", 2.0)
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/series/bcrd.test.serie", params={"with_ai": "true"})
    assert r.status_code == 200
    ai = r.json()["ai_insight"]
    # No API key in tests → static fallback (best-effort never breaks the endpoint).
    assert ai is not None
    assert "text" in ai and ai["text"]
    assert ai["model_used"] == "static_fallback"


def test_series_with_ai_true_empty_series_skips(db):
    # No observations → no insight attempted (and no crash).
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/series/bcrd.absent", params={"with_ai": "true"})
    assert r.status_code == 200
    assert r.json()["ai_insight"] is None
