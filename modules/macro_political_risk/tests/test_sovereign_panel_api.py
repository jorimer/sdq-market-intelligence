"""Tests del panel soberano (API): lectura multi-agencia + anotación de afirmación.

La superficie donde se completa la propuesta de frescura ("verificar el rating y anotar
la afirmación"): ver el panel (cualquier autenticado), anotar (solo admin, solo store).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.contracts.sovereign_ratings import save_sovereign_ratings
from shared.database.base import Base
from shared.database.session import get_db
from shared.settings.models import AppSetting
from modules.macro_political_risk.api.router_scoring import router


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _U:
    def __init__(self, role):
        self.id = "u1"
        self.role = role


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/macro-political-risk")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def _seed(db):
    save_sovereign_ratings(db, {
        "DO": {"sp": {"rating": "BB", "outlook": "estable",
                      "action_date": "2022-12-19", "affirm_date": None}},
    })


def test_panel_lists_store_and_floor(db):
    _seed(db)
    r = _client(db).get("/api/v1/macro-political-risk/sovereign-panel")
    assert r.status_code == 200
    body = r.json()
    by_iso = {c["iso"]: c for c in body["countries"]}
    assert by_iso["DO"]["in_store"] is True and by_iso["DO"]["stale"] is True
    # CR viene del piso declarado (yaml): visible pero NO anotable.
    assert by_iso["CR"]["in_store"] is False
    anchor = next(a for a in by_iso["DO"]["agencies"] if a["is_anchor"])
    assert anchor["rating"] == "BB" and anchor["action_date"] == "2022-12-19"
    assert body["anchor_agency"] == "sp" and body["can_annotate"] is True


def test_panel_viewer_cannot_annotate(db):
    _seed(db)
    r = _client(db, role=UserRole.viewer).get("/api/v1/macro-political-risk/sovereign-panel")
    assert r.status_code == 200 and r.json()["can_annotate"] is False


def test_affirm_admin_annotates_and_silences(db):
    _seed(db)
    c = _client(db)
    r = c.post("/api/v1/macro-political-risk/sovereign-panel/do/affirm",
               json={"affirm_date": "2026-06-15"})
    assert r.status_code == 200 and r.json()["iso"] == "DO"
    body = c.get("/api/v1/macro-political-risk/sovereign-panel").json()
    do = next(x for x in body["countries"] if x["iso"] == "DO")
    anchor = next(a for a in do["agencies"] if a["is_anchor"])
    assert anchor["affirm_date"] == "2026-06-15"
    assert do["stale"] is False  # la afirmación silencia la propuesta de frescura


def test_affirm_requires_admin(db):
    _seed(db)
    r = _client(db, role=UserRole.analyst).post(
        "/api/v1/macro-political-risk/sovereign-panel/DO/affirm",
        json={"affirm_date": "2026-06-15"})
    assert r.status_code == 403


def test_affirm_invalid_date_and_missing_country(db):
    _seed(db)
    c = _client(db)
    assert c.post("/api/v1/macro-political-risk/sovereign-panel/DO/affirm",
                  json={"affirm_date": "15/06/2026"}).status_code == 422
    assert c.post("/api/v1/macro-political-risk/sovereign-panel/CR/affirm",
                  json={"affirm_date": "2026-06-15"}).status_code == 404
