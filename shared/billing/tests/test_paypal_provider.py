"""Tests del adaptador PayPal (sin red): custom_id, is_configured, parse_event, guards."""
import pytest

from shared.billing.providers.base import ProviderNotConfigured
from shared.billing.providers.paypal import (
    PayPalProvider,
    decode_custom_id,
    encode_custom_id,
)

CFG_OK = {"enabled": True, "client_id": "cid", "secret": "sec", "env": "sandbox",
          "webhook_id": "WH", "plans": {"pro": "P-PRO", "enterprise": ""}}
CFG_OFF = {"enabled": False, "plans": {}}


def test_custom_id_roundtrip():
    cid = encode_custom_id("u1", "order", "deep_dive:banking")
    assert decode_custom_id(cid) == ("u1", "order", "deep_dive:banking")
    assert decode_custom_id("garbage") is None
    assert decode_custom_id("") is None


def test_is_configured():
    assert PayPalProvider(CFG_OK).is_configured() is True
    assert PayPalProvider(CFG_OFF).is_configured() is False


def test_checkout_requires_config():
    p = PayPalProvider(CFG_OFF)
    with pytest.raises(ProviderNotConfigured):
        p.create_order_checkout(sku="deep_dive:banking", amount="10.00", currency="USD",
                                user_id="u1", return_url="r", cancel_url="c")
    with pytest.raises(ProviderNotConfigured):
        p.create_subscription_checkout(tier="pro", user_id="u1", return_url="r", cancel_url="c")


def test_subscription_requires_plan_id():
    # enterprise no tiene plan configurado → error claro, no llamada a red.
    with pytest.raises(ProviderNotConfigured, match="enterprise"):
        PayPalProvider(CFG_OK).create_subscription_checkout(
            tier="enterprise", user_id="u1", return_url="r", cancel_url="c")


def test_parse_order_paid():
    p = PayPalProvider(CFG_OK)
    ev = p.parse_event({
        "id": "EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": "CAP-1", "custom_id": encode_custom_id("u9", "order", "deep_dive:macro")},
    })
    assert ev.kind == "order_paid" and ev.user_id == "u9" and ev.sku == "deep_dive:macro"
    assert ev.event_id == "EVT-1" and ev.provider_ref == "CAP-1"


def test_parse_order_custom_id_in_purchase_units():
    p = PayPalProvider(CFG_OK)
    ev = p.parse_event({
        "id": "EVT-2", "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "ORD-2",
                     "purchase_units": [{"custom_id": encode_custom_id("u1", "order", "deep_dive:banking")}]},
    })
    assert ev.kind == "order_paid" and ev.user_id == "u1" and ev.sku == "deep_dive:banking"


def test_parse_subscription_lifecycle():
    p = PayPalProvider(CFG_OK)
    base = {"resource": {"id": "SUB-1", "custom_id": encode_custom_id("u1", "sub", "pro"),
                         "billing_info": {"next_billing_time": "2026-12-31T00:00:00Z"}}}
    act = p.parse_event({**base, "id": "E1", "event_type": "BILLING.SUBSCRIPTION.ACTIVATED"})
    assert act.kind == "subscription_active" and act.tier == "pro" and act.period_end.startswith("2026-12-31")
    can = p.parse_event({**base, "id": "E2", "event_type": "BILLING.SUBSCRIPTION.CANCELLED"})
    assert can.kind == "subscription_cancelled"
    exp = p.parse_event({**base, "id": "E3", "event_type": "BILLING.SUBSCRIPTION.EXPIRED"})
    assert exp.kind == "subscription_expired"


def test_parse_ignores_irrelevant_event():
    assert PayPalProvider(CFG_OK).parse_event({"id": "E", "event_type": "SOMETHING.ELSE"}) is None


def test_capture_requires_config():
    with pytest.raises(ProviderNotConfigured):
        PayPalProvider(CFG_OFF).capture_order("ORD-1")
