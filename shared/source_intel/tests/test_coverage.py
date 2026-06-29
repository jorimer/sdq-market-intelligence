"""Tests del detector de cobertura + auto-diferir (Capa 3 — auto-marcado).

Aísla la lógica mockeando ``build_audit``: una sugerencia para un eje cuyo g1 (datos)
ya está en pleno se marca ``already_covered`` y se auto-difiere; las de un eje con g1
abierto NO se tocan, y una decisión ya tomada (approved) tampoco.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.audit as audit_mod
from shared.database.base import Base
from shared.source_intel.coverage import coverage_status
from shared.source_intel.models import SourceSuggestion
from shared.source_intel.service import (
    create_suggestion,
    flag_covered_decided,
    reflag_covered_suggestions,
    set_status,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SourceSuggestion.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


# energy: g1 en pleno (sin brecha g1) → cubierto. telecom: g1 abierto → NO cubierto.
# construction: g1 PARCIAL (brecha g1 abierta) → NO cubierto (su fuente aún ayuda).
_AUDIT = {"sectors": [
    {"sector_key": "energy", "display_name": "Energy", "implemented": True,
     "gaps": [{"gate": "g5", "label": "Validación", "value": 0.45,
               "falta": "sin backtest", "accion": "backtest"}]},
    {"sector_key": "telecom", "display_name": "Telecom", "implemented": True,
     "gaps": [{"gate": "g1", "label": "Datos", "value": 0.0,
               "falta": "congelado", "accion": "cargar"}]},
    {"sector_key": "construction", "display_name": "Construction", "implemented": True,
     "gaps": [{"gate": "g1", "label": "Datos", "value": 0.82,
               "falta": "3 variables en rúbrica", "accion": "subir a dato real"}]},
    {"sector_key": "newsector", "display_name": "New", "implemented": False, "gaps": []},
]}


@pytest.fixture(autouse=True)
def _mock_audit(monkeypatch):
    monkeypatch.setattr(audit_mod, "build_audit", lambda db: _AUDIT)


def test_coverage_status_covered_when_g1_full(db):
    cov = coverage_status(db, "energy")
    assert cov["covered"] is True and "cobertura plena" in cov["note"]


def test_coverage_status_not_covered_when_g1_open(db):
    assert coverage_status(db, "telecom")["covered"] is False
    assert coverage_status(db, "construction")["covered"] is False  # g1 parcial 0.82


def test_coverage_status_unknown_or_none_axis(db):
    assert coverage_status(db, None)["covered"] is False
    assert coverage_status(db, "nope")["covered"] is False
    assert coverage_status(db, "newsector")["covered"] is False  # no implementado


def test_reflag_defers_covered_open_suggestions(db):
    covered = create_suggestion(db, kind="source", title="Boletín energy",
                                description="d", origin="agent",
                                target_axis="energy", target_gate="g5")
    open_gap = create_suggestion(db, kind="source", title="Fuente telecom",
                                 description="d", origin="agent",
                                 target_axis="telecom", target_gate="g1")
    # una ya decidida sobre un eje cubierto NO debe re-tocarse
    decided = create_suggestion(db, kind="source", title="Energy aprobada",
                                description="d", origin="manual",
                                target_axis="energy", target_gate="g1")
    set_status(db, decided["id"], "approved")

    changed = reflag_covered_suggestions(db)
    assert changed == [covered["id"]]

    c = db.query(SourceSuggestion).filter_by(id=covered["id"]).one()
    assert c.status == "deferred"
    assert c.evaluation["already_covered"] is True
    assert "Auto-diferida" in (c.decision_note or "")

    assert db.query(SourceSuggestion).filter_by(id=open_gap["id"]).one().status == "proposed"
    assert db.query(SourceSuggestion).filter_by(id=decided["id"]).one().status == "approved"


def test_reflag_is_idempotent(db):
    create_suggestion(db, kind="source", title="Boletín energy", description="d",
                      origin="agent", target_axis="energy", target_gate="g5")
    assert len(reflag_covered_suggestions(db)) == 1
    assert reflag_covered_suggestions(db) == []  # ya diferida → no re-toca


def test_flag_covered_decided_badges_without_moving(db):
    # aprobada sobre eje cubierto → se marca (badge) pero NO cambia de estado
    cov = create_suggestion(db, kind="source", title="Energy aprobada", description="d",
                            origin="manual", target_axis="energy", target_gate="g1")
    set_status(db, cov["id"], "approved")
    # aprobada sobre eje con g1 abierto → no se marca
    open_ax = create_suggestion(db, kind="source", title="Telecom aprobada", description="d",
                                origin="manual", target_axis="telecom", target_gate="g1")
    set_status(db, open_ax["id"], "approved")

    flagged = flag_covered_decided(db)
    assert flagged == [cov["id"]]
    c = db.query(SourceSuggestion).filter_by(id=cov["id"]).one()
    assert c.status == "approved"  # NO se mueve: el dueño confirma integrada/diferir
    assert c.evaluation["already_covered"] is True
    o = db.query(SourceSuggestion).filter_by(id=open_ax["id"]).one()
    assert (o.evaluation or {}).get("already_covered") in (None, False)
    assert flag_covered_decided(db) == []  # idempotente
