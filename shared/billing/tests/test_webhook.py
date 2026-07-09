"""Tests del despacho de webhooks: verificación, idempotencia y mapeo al acceso.

Usa un proveedor STUB (sin red) que verifica siempre y parsea un evento fijo, para probar la
lógica de handle_webhook (dedupe + aplicación a entitlement/suscripción)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.billing import webhook as wh
from shared.billing.models import BillingEvent
from shared.billing.providers.base import NormalizedEvent
from shared.products.models import ProductEntitlement, Subscription
from shared.products.subscriptions import active_subscription_tier
from shared.auth.models import AccessTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        BillingEvent.__table__, ProductEntitlement.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _StubProvider:
    """Proveedor de prueba: configurado, firma OK, devuelve el evento inyectado."""

    def __init__(self, event, configured=True, verifies=True):
        self._event = event
        self._configured = configured
        self._verifies = verifies

    def is_configured(self):
        return self._configured

    def verify_webhook(self, *, headers, body):
        return self._verifies

    def parse_event(self, payload):
        return self._event


def _patch(monkeypatch, event, **kw):
    monkeypatch.setattr(wh, "get_provider", lambda db, name: _StubProvider(event, **kw))


def test_order_paid_grants_entitlement(monkeypatch, db):
    ev = NormalizedEvent(event_id="E1", kind="order_paid", provider_ref="CAP-1",
                         user_id="u1", sku="deep_dive:banking")
    _patch(monkeypatch, ev)
    res = wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "E1"}).encode())
    assert res["status"] == "applied" and res["result"] == "entitlement_otorgado"
    ent = db.query(ProductEntitlement).one()
    assert ent.sector_key == "banking" and ent.tier == "deep_dive" and ent.source == "order"


def test_subscription_active_grants_tier(monkeypatch, db):
    ev = NormalizedEvent(event_id="E2", kind="subscription_active", provider_ref="SUB-1",
                         user_id="u1", tier="pro")
    _patch(monkeypatch, ev)
    wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "E2"}).encode())
    assert active_subscription_tier(db, "u1") == AccessTier.pro


def test_subscription_cancel_cuts_access(monkeypatch, db):
    _patch(monkeypatch, NormalizedEvent(event_id="A", kind="subscription_active",
                                        provider_ref="SUB-9", user_id="u1", tier="enterprise"))
    wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "A"}).encode())
    assert active_subscription_tier(db, "u1") == AccessTier.enterprise
    _patch(monkeypatch, NormalizedEvent(event_id="B", kind="subscription_cancelled",
                                        provider_ref="SUB-9", user_id="u1", tier="enterprise"))
    wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "B"}).encode())
    assert active_subscription_tier(db, "u1") is None


def test_idempotent_dedupe(monkeypatch, db):
    ev = NormalizedEvent(event_id="DUP", kind="order_paid", provider_ref="C",
                         user_id="u1", sku="deep_dive:macro")
    _patch(monkeypatch, ev)
    body = json.dumps({"id": "DUP"}).encode()
    first = wh.handle_webhook(db, "paypal", {}, body)
    second = wh.handle_webhook(db, "paypal", {}, body)
    assert first["status"] == "applied" and second["status"] == "duplicate"
    assert db.query(ProductEntitlement).count() == 1  # no dobló el acceso


def test_not_configured_ignored(monkeypatch, db):
    _patch(monkeypatch, None, configured=False)
    res = wh.handle_webhook(db, "paypal", {}, b"{}")
    assert res["status"] == "ignored" and res["reason"] == "provider_not_configured"


def test_bad_signature_rejected(monkeypatch, db):
    _patch(monkeypatch, None, verifies=False)
    with pytest.raises(wh.WebhookError):
        wh.handle_webhook(db, "paypal", {}, b"{}")


def test_irrelevant_event_ignored(monkeypatch, db):
    _patch(monkeypatch, None)  # parse_event → None
    res = wh.handle_webhook(db, "paypal", {}, b"{}")
    assert res["status"] == "ignored" and res["reason"] == "event_not_relevant"
