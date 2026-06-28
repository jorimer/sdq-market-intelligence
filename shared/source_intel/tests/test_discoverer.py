"""Tests del descubridor de catálogos (Capa 3, frontera).

Aísla la orquestación: mockea el audit (brechas), el ``_ckan_search`` (la API real) y el
evaluador. Verifica creación de datasets reales (origin=catalog), dedup por brecha/título,
cap y aviso.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.audit as audit_mod
import shared.source_intel.discoverer as disc
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
    {"sector_key": "energy", "display_name": "Energy", "implemented": True,
     "gaps": [{"gate": "g1", "label": "Datos", "value": 0.65, "falta": "x", "accion": "y"}]},
    {"sector_key": "banking", "display_name": "Banking", "implemented": True, "gaps": []},
]}


def _wire(monkeypatch):
    monkeypatch.setattr(audit_mod, "build_audit", lambda db: _AUDIT)
    monkeypatch.setattr(disc, "_ckan_search", lambda q, rows=3: [
        {"title": "Estadísticas de Energía Entregada y Pérdida 2017-2026", "org": "EDE",
         "notes": "energía entregada y pérdida", "formats": ["CSV"],
         "url": "https://datos.gob.do/dataset/energia-perdida"},
        {"title": "Total de Energía Facturada", "org": "CDEEE", "notes": "facturación",
         "formats": ["CSV"], "url": "https://datos.gob.do/dataset/energia-facturada"}])
    monkeypatch.setattr(evaluator, "evaluate_suggestion", lambda db, s: {
        "score": 0.7, "criteria": {}, "gate_closed": s.get("target_gate"),
        "fit_rationale": "x", "recommendation": "investigate", "method": "ai"})


def _admin(db):
    db.add(User(email="a@x.com", password_hash="x", full_name="A",
                role=UserRole.admin, is_active=True))
    db.commit()


def test_discovers_real_datasets(db, monkeypatch):
    _wire(monkeypatch)
    _admin(db)
    res = disc.run_catalog_discovery(db)
    assert res["created"] == 2
    rows = db.query(SourceSuggestion).all()
    assert len(rows) == 2
    s = rows[0]
    assert s.origin == "catalog" and s.target_axis == "energy" and s.target_gate == "g1"
    assert "datos.gob.do" in s.description and s.status == "evaluated"
    assert db.query(Notification).count() == 1


def test_discoverer_dedups_by_title(db, monkeypatch):
    _wire(monkeypatch)
    disc.run_catalog_discovery(db)
    # 2ª corrida: misma brecha (energy/g1) ya abierta → no re-descubre
    res = disc.run_catalog_discovery(db)
    assert res["created"] == 0
    assert db.query(SourceSuggestion).count() == 2


def test_discoverer_reports_cap(db, monkeypatch):
    _wire(monkeypatch)
    res = disc.run_catalog_discovery(db, max_create=1)
    assert res["created"] == 1 and res["capped"] is True


def test_ckan_search_failure_is_safe(db, monkeypatch):
    """Una búsqueda CKAN que falla devuelve [] (no rompe el run)."""
    monkeypatch.setattr(audit_mod, "build_audit", lambda db: _AUDIT)
    monkeypatch.setattr(disc, "_ckan_search", lambda q, rows=3: [])
    res = disc.run_catalog_discovery(db)
    assert res["created"] == 0
