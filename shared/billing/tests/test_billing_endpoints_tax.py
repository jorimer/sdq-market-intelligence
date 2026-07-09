"""Tests de endpoint del checkout con impuestos y del lazo de cancelación / gating por período.

Corre el router real con overrides de ``get_db`` / ``get_current_user`` (como producción)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.billing.models  # noqa: F401
import shared.products.models  # noqa: F401
import shared.settings.models  # noqa: F401
from shared.auth.dependencies import get_current_user
from shared.auth.models import AccessTier, UserRole
from shared.billing.router import router
from shared.billing.tariffs import create_tariff
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.models import Subscription
from shared.products.subscriptions import active_subscription_tier, subscription_grants


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _client(db, uid="u1", role=UserRole.admin, country=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/billing")

    class _U:
        def __init__(self):
            self.id = uid
            self.role = role
            self.country = country

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U()
    return TestClient(app)


def test_quote_rd_includes_itbis(db):
    c = _client(db, country="DO")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    r = c.post("/api/v1/billing/checkout/quote", json={"sku": "deep_dive:banking", "interval": "once"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subtotal"] == "100.00" and body["tax"] == "18.00" and body["total"] == "118.00"


def test_quote_foreign_is_exempt(db):
    c = _client(db, country="DO")
    create_tariff(db, sku="insight:banking", amount="50.00", currency="USD", interval="monthly")
    r = c.post("/api/v1/billing/checkout/quote",
               json={"sku": "insight:banking", "interval": "monthly", "country": "US"})
    assert r.status_code == 200, r.text
    assert r.json()["tax"] == "0.00" and r.json()["exempt"] is True


def test_quote_404_without_price(db):
    c = _client(db, country="DO")
    r = c.post("/api/v1/billing/checkout/quote", json={"sku": "deep_dive:banking"})
    assert r.status_code == 404


def test_tax_config_admin_roundtrip(db):
    c = _client(db, role=UserRole.admin)
    r = c.put("/api/v1/billing/tax", json={"rate": "16", "label": "IVA", "home_country": "MX"})
    assert r.status_code == 200 and r.json()["rate"] == "16" and r.json()["home_country"] == "MX"
    assert c.get("/api/v1/billing/tax").json()["label"] == "IVA"


def test_tax_config_forbidden_for_viewer(db):
    c = _client(db, role=UserRole.viewer)
    assert c.get("/api/v1/billing/tax").status_code == 403


def test_cancel_manual_subscription(db):
    # Suscripción manual (sin pasarela): la baja no toca PayPal.
    sub = Subscription(id="s1", user_id="u1", provider="manual",
                       provider_subscription_id="m1", sku="all_access", tier="pro", status="active")
    db.add(sub)
    db.commit()
    c = _client(db, uid="u1")
    r = c.post("/api/v1/billing/subscription/s1/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert active_subscription_tier(db, "u1") is None


def test_cannot_cancel_someone_elses_subscription(db):
    sub = Subscription(id="s2", user_id="other", provider="manual",
                       provider_subscription_id="m2", sku="all_access", tier="pro", status="active")
    db.add(sub)
    db.commit()
    c = _client(db, uid="u1")
    assert c.post("/api/v1/billing/subscription/s2/cancel").status_code == 404


def test_active_sub_with_expired_period_grants_nothing(db):
    # §3.D: una suscripción 'active' con período vencido NO concede acceso (gating por período).
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.add(Subscription(id="s3", user_id="u1", provider="paypal", provider_subscription_id="p3",
                        sku="insight:banking", tier="pro", status="active",
                        current_period_end=past))
    db.commit()
    assert active_subscription_tier(db, "u1") is None
    assert subscription_grants(db, "u1", "banking", "insight") is False
