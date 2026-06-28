"""Tests del detector de mejoras (Capa 2): avisa cuando un nivel cruza a publicable.

El sistema PROPONE (notifica a admins «X ya es publicable»); el dueño DISPONE (activa a
mano). Se prueba la detección de cruces en ``recompute_readiness`` y la lógica de aviso
(agrupar por sector, deduplicar, limpiar al caer, no avisar en el primer cálculo).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.service as svc
from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.tiers import ProductTier
from shared.settings.models import AppSetting


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        ProductReadiness.__table__, ProductActivation.__table__,
        User.__table__, Notification.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _admin(db, email="a@x.com"):
    u = User(email=email, password_hash="x", full_name="A",
             role=UserRole.admin, is_active=True)
    db.add(u)
    db.commit()
    return u


def _seed_readiness(db, sector, tier, readiness):
    db.add(ProductReadiness(sector_key=sector, tier=tier, readiness=readiness,
                            g1=readiness, g2=readiness, g3=readiness, g4=readiness, g5=readiness))
    db.commit()


def test_notify_groups_dedups_and_clears(db):
    _admin(db)
    # Dos niveles del mismo sector cruzan → UN aviso agrupado.
    svc._notify_publishable_transitions(db, up=[
        ("banking", ProductTier.insight, 0.9), ("banking", ProductTier.deep_dive, 0.9)], down=[])
    notes = db.query(Notification).all()
    assert len(notes) == 1
    assert "insight" in notes[0].body and "deep_dive" in notes[0].body
    assert "manual" in notes[0].body.lower()
    # Re-correr el mismo cruce → dedup por marcador (sin aviso nuevo).
    svc._notify_publishable_transitions(db, up=[("banking", ProductTier.insight, 0.9)], down=[])
    assert db.query(Notification).count() == 1
    # Cae bajo el umbral → limpia el marcador; vuelve a cruzar → re-avisa.
    svc._notify_publishable_transitions(db, up=[], down=[("banking", ProductTier.insight)])
    svc._notify_publishable_transitions(db, up=[("banking", ProductTier.insight, 0.9)], down=[])
    assert db.query(Notification).count() == 2


def test_notify_noop_without_admins(db):
    svc._notify_publishable_transitions(db, up=[("banking", ProductTier.pulse, 0.9)], down=[])
    assert db.query(Notification).count() == 0


def test_recompute_detects_crossing_and_notifies(db, monkeypatch):
    _admin(db)
    _seed_readiness(db, "banking", "pulse", 0.50)  # base previa BAJO el umbral 0.75
    monkeypatch.setattr(svc, "get_product", lambda k, d: object())
    monkeypatch.setattr(svc, "_tiers_for", lambda p: [ProductTier.pulse])
    monkeypatch.setattr(svc, "compute_readiness", lambda p, t: {
        "sector_key": "banking", "tier": "pulse", "g1": 1, "g2": 1, "g3": 1, "g4": 1,
        "g5": 1, "readiness": 0.90, "detail": {}})
    svc.recompute_readiness(db, sector_key="banking")
    notes = db.query(Notification).all()
    assert len(notes) == 1 and "Banking" in notes[0].title


def test_recompute_no_alert_on_first_computation(db, monkeypatch):
    """Sin fila previa (primer cálculo) NO se avisa, aunque salga publicable — evita el
    spam de arranque cuando se siembra el readiness por primera vez."""
    _admin(db)  # sin _seed_readiness → no hay base previa
    monkeypatch.setattr(svc, "get_product", lambda k, d: object())
    monkeypatch.setattr(svc, "_tiers_for", lambda p: [ProductTier.pulse])
    monkeypatch.setattr(svc, "compute_readiness", lambda p, t: {
        "sector_key": "banking", "tier": "pulse", "g1": 1, "g2": 1, "g3": 1, "g4": 1,
        "g5": 1, "readiness": 0.90, "detail": {}})
    svc.recompute_readiness(db, sector_key="banking")
    assert db.query(Notification).count() == 0
