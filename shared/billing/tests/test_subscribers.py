"""Tests del resolver de audiencia de alertas de tarifa (shared/billing/subscribers).

Modelo v2: los afectados por un cambio de precio son los tenedores de una ``Subscription``
ACTIVA de ese SKU. Compras puntuales (deep_dive/special) → sin suscriptores → vacío.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import AccessTier, User, UserRole
from shared.billing.subscribers import affected_subscribers
from shared.database.base import Base
from shared.products.models import Subscription
from shared.products.subscriptions import set_manual_subscription


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _user(db, email, is_active=True):
    u = User(email=email, password_hash="x", full_name=email, role=UserRole.viewer,
             tier=AccessTier.free, is_active=is_active)
    db.add(u)
    db.commit()
    return u


def test_targets_active_subscribers_of_that_sku(db):
    a = _user(db, "a@x")
    b = _user(db, "b@x")
    c = _user(db, "c@x")  # suscripto a OTRO sku → no afectado
    set_manual_subscription(db, user_id=a.id, sku="insight:banking")
    set_manual_subscription(db, user_id=b.id, sku="insight:banking")
    set_manual_subscription(db, user_id=c.id, sku="insight:macro")
    ids = {u.id for u in affected_subscribers(db, "insight:banking")}
    assert ids == {a.id, b.id}


def test_cancelled_subscriber_not_targeted(db):
    a = _user(db, "a@x")
    row = set_manual_subscription(db, user_id=a.id, sku="all_access")
    from shared.products.subscriptions import cancel_subscription
    cancel_subscription(db, row["id"])
    assert affected_subscribers(db, "all_access") == []


def test_deep_dive_and_special_have_no_recurring_subscribers(db):
    _user(db, "a@x")
    assert affected_subscribers(db, "deep_dive:banking") == []
    assert affected_subscribers(db, "special:algo") == []


def test_invalid_sku_returns_empty(db):
    assert affected_subscribers(db, "basura") == []
