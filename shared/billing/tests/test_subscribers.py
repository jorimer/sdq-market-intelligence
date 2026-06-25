"""Tests del resolver de audiencia de alertas de tarifa (shared/billing/subscribers).

Hoy (sin modelo de suscripción formal): solo ``insight`` tiene suscriptores recurrentes
= usuarios con tier pro/enterprise ACTIVOS. Compras puntuales (deep_dive/special) → vacío.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import AccessTier, User, UserRole
from shared.billing.subscribers import affected_subscribers
from shared.database.base import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _user(db, email, tier, is_active=True):
    u = User(email=email, password_hash="x", full_name=email, role=UserRole.viewer,
             tier=tier, is_active=is_active)
    db.add(u)
    db.commit()
    return u


def test_insight_targets_active_pro_and_enterprise(db):
    _user(db, "free@x", AccessTier.free)
    pro = _user(db, "pro@x", AccessTier.pro)
    ent = _user(db, "ent@x", AccessTier.enterprise)
    _user(db, "inactivo@x", AccessTier.pro, is_active=False)
    ids = {u.id for u in affected_subscribers(db, "insight")}
    assert ids == {pro.id, ent.id}


def test_deep_dive_has_no_recurring_subscribers(db):
    _user(db, "pro@x", AccessTier.pro)
    assert affected_subscribers(db, "deep_dive:banking") == []


def test_special_has_no_recurring_subscribers(db):
    _user(db, "ent@x", AccessTier.enterprise)
    assert affected_subscribers(db, "special:algo") == []


def test_invalid_sku_returns_empty(db):
    _user(db, "pro@x", AccessTier.pro)
    assert affected_subscribers(db, "basura") == []
