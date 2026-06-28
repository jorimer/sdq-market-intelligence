"""Tests del agente de descubrimiento de fuentes (Capa 3 Increment 3).

Se aísla la orquestación: se mockean el audit (las brechas) y el proposer/evaluator
(las llamadas a Claude), y se verifica creación + auto-evaluación + dedup por brecha +
no-op sin IA + aviso a admins.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.audit as audit_mod
import shared.source_intel.agent as agent
import shared.source_intel.evaluator as evaluator
from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.source_intel.models import SourceSuggestion


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        SourceSuggestion.__table__, User.__table__, Notification.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


_AUDIT = {"sectors": [
    {"sector_key": "telecom", "display_name": "Telecom", "implemented": True,
     "gaps": [{"gate": "g1", "label": "Datos", "value": 0.0,
               "falta": "INDOTEL congelado 2022", "accion": "cargar boletín vigente"}]},
    {"sector_key": "energy", "display_name": "Energy", "implemented": True, "gaps": []},
    {"sector_key": "x", "display_name": "X", "implemented": False, "gaps": []},
]}


def _wire(monkeypatch):
    monkeypatch.setattr(agent.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(audit_mod, "build_audit", lambda db: _AUDIT)
    monkeypatch.setattr(agent, "_propose_sources", lambda axis, disp, gap: [
        {"kind": "source", "title": f"Boletín {axis}", "description": "d", "target_gate": gap["gate"]}])
    # auto-eval sin red: el evaluador devuelve una evaluación canned
    monkeypatch.setattr(evaluator, "evaluate_suggestion", lambda db, s: {
        "score": 0.6, "criteria": {}, "gate_closed": s.get("target_gate"),
        "fit_rationale": "x", "recommendation": "investigate", "method": "ai"})


def _admin(db):
    db.add(User(email="a@x.com", password_hash="x", full_name="A",
                role=UserRole.admin, is_active=True))
    db.commit()


def test_agent_creates_evaluates_and_notifies(db, monkeypatch):
    _wire(monkeypatch)
    _admin(db)
    res = agent.run_research_agent(db)
    assert res["created"] == 1 and res["evaluated"] == 1
    rows = db.query(SourceSuggestion).all()
    assert len(rows) == 1
    s = rows[0]
    assert s.origin == "agent" and s.target_axis == "telecom" and s.status == "evaluated"
    assert s.evaluation and s.evaluation["method"] == "ai"
    assert db.query(Notification).count() == 1  # avisó a la admin


def test_agent_is_idempotent_per_gap(db, monkeypatch):
    _wire(monkeypatch)
    agent.run_research_agent(db)
    # 2ª corrida: la brecha (telecom, g1) ya tiene propuesta abierta → no re-propone
    res2 = agent.run_research_agent(db)
    assert res2["created"] == 0 and res2["skipped_gaps"] == 1
    assert db.query(SourceSuggestion).count() == 1


def test_agent_reproposes_after_rejection(db, monkeypatch):
    _wire(monkeypatch)
    agent.run_research_agent(db)
    s = db.query(SourceSuggestion).first()
    s.status = "rejected"  # cerrada → el agente puede volver a proponer
    db.commit()
    res = agent.run_research_agent(db)
    assert res["created"] == 1


def test_agent_no_ai_is_honest_noop(db, monkeypatch):
    monkeypatch.setattr(audit_mod, "build_audit", lambda db: _AUDIT)
    monkeypatch.setattr(agent.settings, "ANTHROPIC_API_KEY", None, raising=False)
    res = agent.run_research_agent(db)
    assert res["created"] == 0 and "sin IA" in res["reason"]
    assert db.query(SourceSuggestion).count() == 0
