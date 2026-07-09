"""Tests del adaptador PayPal en el eje MONTO: se le pasa el TOTAL (subtotal + impuesto), la
orden lleva el desglose y la suscripción el override de impuesto. Sin red: se intercepta
``_post`` para capturar el body que se le mandaría a PayPal."""
import pytest

from shared.billing.providers.paypal import PayPalProvider

_CFG = {"enabled": True, "client_id": "cid", "secret": "sec", "env": "sandbox",
        "plans": {"insight:banking": {"monthly": "P-MONTH-1", "annual": "P-YEAR-1"}}}


class _Capture:
    def __init__(self):
        self.path = None
        self.body = None

    def __call__(self, path, body, token=None):
        self.path, self.body = path, body
        # Respuestas mínimas por endpoint.
        if path.endswith("/capture"):
            return {"status": "COMPLETED", "id": "ORD-1"}
        return {"id": "ORD-1", "links": [{"rel": "approve", "href": "https://paypal/approve"}]}


@pytest.fixture()
def provider(monkeypatch):
    p = PayPalProvider(_CFG)
    cap = _Capture()
    monkeypatch.setattr(p, "_post", cap)
    return p, cap


def test_order_sends_total_with_breakdown(provider):
    p, cap = provider
    ck = p.create_order_checkout(sku="deep_dive:banking", amount="118.00", currency="USD",
                                 user_id="u1", return_url="r", cancel_url="c",
                                 subtotal="100.00", tax="18.00")
    assert ck.approval_url == "https://paypal/approve"
    amt = cap.body["purchase_units"][0]["amount"]
    assert amt["value"] == "118.00"  # TOTAL, no el subtotal
    bd = amt["breakdown"]
    assert bd["item_total"]["value"] == "100.00" and bd["tax_total"]["value"] == "18.00"


def test_order_without_tax_has_no_breakdown_mismatch(provider):
    p, cap = provider
    p.create_order_checkout(sku="deep_dive:banking", amount="100.00", currency="USD",
                            user_id="u1", return_url="r", cancel_url="c",
                            subtotal="100.00", tax="0")
    bd = cap.body["purchase_units"][0]["amount"]["breakdown"]
    # item_total + tax_total == value (PayPal rechaza un desglose que no suma).
    assert float(bd["item_total"]["value"]) + float(bd["tax_total"]["value"]) == 100.00


def test_subscription_applies_tax_override(provider):
    p, cap = provider
    p.create_subscription_checkout(sku="insight:banking", interval="monthly", user_id="u1",
                                   return_url="r", cancel_url="c", tax_percentage="18")
    assert cap.body["plan_id"] == "P-MONTH-1"
    assert cap.body["plan"]["taxes"] == {"percentage": "18", "inclusive": False}


def test_subscription_exempt_has_no_tax_override(provider):
    p, cap = provider
    p.create_subscription_checkout(sku="insight:banking", interval="annual", user_id="u1",
                                   return_url="r", cancel_url="c", tax_percentage="0")
    assert cap.body["plan_id"] == "P-YEAR-1"
    assert "plan" not in cap.body  # 0% → no se manda override


def test_cancel_hits_paypal_cancel_endpoint(provider):
    p, cap = provider
    p.cancel_subscription("SUB-42", reason="cliente")
    assert cap.path == "/v1/billing/subscriptions/SUB-42/cancel"
    assert cap.body["reason"] == "cliente"


def test_interval_resolved_from_plan_id():
    p = PayPalProvider(_CFG)
    assert p._interval_for_plan("insight:banking", "P-YEAR-1") == "annual"
    assert p._interval_for_plan("insight:banking", "P-MONTH-1") == "monthly"
    assert p._interval_for_plan("insight:banking", "P-UNKNOWN") is None


def test_capture_order_parses_payer_and_gross(monkeypatch):
    p = PayPalProvider(_CFG)
    monkeypatch.setattr(p, "_post", lambda path, body, token=None: {
        "id": "ORD-1", "status": "COMPLETED",
        "purchase_units": [{
            "custom_id": "user-7|order|deep_dive:banking",
            "payments": {"captures": [{"amount": {"value": "118.00", "currency_code": "USD"}}]},
        }],
    })
    out = p.capture_order("ORD-1")
    assert out["status"] == "COMPLETED" and out["user_id"] == "user-7"
    assert out["sku"] == "deep_dive:banking" and out["gross"] == "118.00" and out["currency"] == "USD"


def test_get_subscription_parses_status_and_custom(monkeypatch):
    p = PayPalProvider(_CFG)
    monkeypatch.setattr(p, "_get", lambda path, token=None: {
        "status": "ACTIVE", "plan_id": "P-MONTH-1",
        "custom_id": "user-9|sub|insight:banking",
        "billing_info": {"next_billing_time": "2026-08-09T00:00:00Z",
                         "last_payment": {"amount": {"value": "59.00", "currency_code": "USD"}}},
    })
    out = p.get_subscription("SUB-1")
    assert out["status"] == "ACTIVE" and out["user_id"] == "user-9"
    assert out["sku"] == "insight:banking" and out["interval"] == "monthly"
    assert out["gross"] == "59.00" and out["period_end"] == "2026-08-09T00:00:00Z"
