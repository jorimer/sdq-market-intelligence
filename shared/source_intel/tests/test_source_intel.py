"""Tests del tablero de Inteligencia de Fuentes (fundación): servicio + API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole, role_satisfies
from shared.database.base import Base
from shared.database.session import get_db
from shared.source_intel import service as svc
from shared.source_intel.models import SourceSuggestion
from shared.source_intel.router import router


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, SourceSuggestion.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


# ── servicio ──────────────────────────────────────────────────────────

def test_create_validates_kind_and_title(db):
    with pytest.raises(svc.SuggestionError):
        svc.create_suggestion(db, kind="nope", title="x")
    with pytest.raises(svc.SuggestionError):
        svc.create_suggestion(db, kind="source", title="   ")
    s = svc.create_suggestion(db, kind="source", title="  Boletín INDOTEL  ",
                              description="trimestral", target_axis="telecom", target_gate="g1")
    assert s["status"] == "proposed" and s["title"] == "Boletín INDOTEL"
    assert s["target_axis"] == "telecom" and s["kind"] == "source"


def test_list_filters_and_summary(db):
    svc.create_suggestion(db, kind="source", title="A", target_axis="telecom")
    svc.create_suggestion(db, kind="sector", title="B")
    assert len(svc.list_suggestions(db)) == 2
    assert len(svc.list_suggestions(db, axis="telecom")) == 1
    assert svc.board_summary(db)["proposed"] == 2


def test_set_status_transitions_and_validates(db):
    s = svc.create_suggestion(db, kind="info_type", title="skills_index por sector")
    moved = svc.set_status(db, s["id"], "approved", decision_note="va")
    assert moved["status"] == "approved" and moved["decision_note"] == "va"
    with pytest.raises(svc.SuggestionError):
        svc.set_status(db, s["id"], "bogus")
    with pytest.raises(svc.SuggestionError):
        svc.set_status(db, "missing-id", "approved")


def test_delete(db):
    s = svc.create_suggestion(db, kind="source", title="x")
    assert svc.delete_suggestion(db, s["id"]) is True
    assert svc.delete_suggestion(db, s["id"]) is False


# ── evaluación IA (Increment 2) — path heurístico determinista ──────────

def _force_heuristic(monkeypatch):
    import shared.source_intel.evaluator as ev
    monkeypatch.setattr(ev.settings, "ANTHROPIC_API_KEY", None, raising=False)


def test_evaluator_heuristic_without_key(db, monkeypatch):
    from shared.source_intel.evaluator import evaluate_suggestion
    _force_heuristic(monkeypatch)
    ev = evaluate_suggestion(db, {"kind": "source", "title": "X", "target_gate": "g1",
                                  "target_axis": None})
    assert ev["method"] == "heuristic"
    assert ev["gate_closed"] == "g1" and ev["recommendation"] == "investigate"
    assert set(ev["criteria"]) == {"coverage", "cadence", "format", "license"}


def test_coerce_normalizes_drift():
    from shared.source_intel.evaluator import _coerce
    out = _coerce({"score": 5, "recommendation": "bogus", "gate_closed": "gZ",
                   "criteria": {"coverage": {"score": "x"}}}, {"target_gate": "g3"})
    assert out["score"] == 1.0                 # clamp
    assert out["recommendation"] == "investigate"
    assert out["gate_closed"] == "g3"          # cae al target del suggestion
    assert out["criteria"]["coverage"]["score"] == 0.5  # no parseable → 0.5
    assert out["method"] == "ai"


def test_evaluate_persists_and_sets_status(db, monkeypatch):
    _force_heuristic(monkeypatch)
    s = svc.create_suggestion(db, kind="source", title="Boletín INDOTEL",
                              target_axis="telecom", target_gate="g1")
    out = svc.evaluate(db, s["id"])
    assert out["status"] == "evaluated"
    assert out["evaluation"]["method"] == "heuristic"
    assert out["evaluation"]["gate_closed"] == "g1"


def test_evaluate_does_not_overwrite_decision(db, monkeypatch):
    _force_heuristic(monkeypatch)
    s = svc.create_suggestion(db, kind="source", title="X")
    svc.set_status(db, s["id"], "approved")
    out = svc.evaluate(db, s["id"])
    assert out["status"] == "approved"         # no pisa una decisión ya tomada
    assert out["evaluation"] is not None       # pero sí adjunta la evaluación


# ── andamiaje de integración (Increment 4) — path heurístico determinista ──

def _force_heuristic_scaffold(monkeypatch):
    import shared.source_intel.scaffolder as sc
    monkeypatch.setattr(sc.settings, "ANTHROPIC_API_KEY", None, raising=False)


def test_scaffold_heuristic_plan(db, monkeypatch):
    _force_heuristic_scaffold(monkeypatch)
    s = svc.create_suggestion(db, kind="source", title="Boletín INDOTEL",
                              target_axis="telecom", target_gate="g1")
    svc.set_status(db, s["id"], "approved")
    out = svc.scaffold(db, s["id"])
    plan = out["integration_plan"]
    assert plan["method"].startswith("heuristic")
    assert "telecom" in plan["target"] and plan["steps"]
    assert out["status"] == "approved"  # andamiar no cambia el estado


# ── API ───────────────────────────────────────────────────────────────

def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/source-intel")

    class _U:
        id = "u1"

        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    # Clave: el role_checker real depende de get_current_user; sobrescribirlo basta para
    # evaluar la jerarquía de roles igual que en producción (require_role no cachea).
    app.dependency_overrides[get_current_user] = lambda: _U(role)

    def _admin_dep():
        u = _U(role)
        if not role_satisfies(u.role, UserRole.admin):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Se requiere rol: admin")
        return u

    app.dependency_overrides[require_role(UserRole.admin)] = _admin_dep
    return TestClient(app)


def test_api_create_list_status_delete(db):
    c = _client(db)
    r = c.post("/api/v1/source-intel/suggestions",
               json={"kind": "source", "title": "Boletín INDOTEL", "target_axis": "telecom"})
    assert r.status_code == 200
    sid = r.json()["id"]
    lst = c.get("/api/v1/source-intel/suggestions").json()
    assert len(lst["suggestions"]) == 1 and lst["summary"]["proposed"] == 1
    assert c.patch(f"/api/v1/source-intel/suggestions/{sid}/status",
                   json={"status": "approved"}).json()["status"] == "approved"
    assert c.delete(f"/api/v1/source-intel/suggestions/{sid}").json()["deleted"] is True
    assert c.get(f"/api/v1/source-intel/suggestions/{sid}").status_code == 404


def test_api_invalid_kind_400(db):
    c = _client(db)
    assert c.post("/api/v1/source-intel/suggestions",
                  json={"kind": "x", "title": "y"}).status_code == 400


def test_api_evaluate(db, monkeypatch):
    _force_heuristic(monkeypatch)
    c = _client(db)
    sid = c.post("/api/v1/source-intel/suggestions",
                 json={"kind": "source", "title": "Boletín INDOTEL", "target_axis": "telecom",
                       "target_gate": "g1"}).json()["id"]
    r = c.post(f"/api/v1/source-intel/suggestions/{sid}/evaluate")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "evaluated" and body["evaluation"]["method"] == "heuristic"


def test_api_requires_admin(db):
    c = _client(db, role=UserRole.analyst)
    assert c.get("/api/v1/source-intel/suggestions").status_code == 403


def test_api_scaffold(db, monkeypatch):
    _force_heuristic_scaffold(monkeypatch)
    c = _client(db)
    sid = c.post("/api/v1/source-intel/suggestions",
                 json={"kind": "source", "title": "X", "target_axis": "telecom",
                       "target_gate": "g1"}).json()["id"]
    r = c.post(f"/api/v1/source-intel/suggestions/{sid}/scaffold")
    assert r.status_code == 200
    assert r.json()["integration_plan"]["method"].startswith("heuristic")
