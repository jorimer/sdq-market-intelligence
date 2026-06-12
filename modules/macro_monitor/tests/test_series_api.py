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
