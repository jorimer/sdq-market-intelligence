"""Tests de la transacción facturable + factura: el webhook persiste el desglose (subtotal +
impuesto = total), la idempotencia no duplica el cobro, el correlativo avanza y la factura
PDF se genera."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Importar todos los modelos para registrar sus tablas en el metadata.
import shared.auth.models  # noqa: F401
import shared.billing.models  # noqa: F401
import shared.products.models  # noqa: F401
import shared.settings.models  # noqa: F401
from shared.auth.models import User
from shared.billing import webhook as wh
from shared.billing.models import BillingTransaction
from shared.billing.providers.base import NormalizedEvent
from shared.billing.tariffs import create_tariff
from shared.billing.tax import TaxBreakdown
from shared.billing.transactions import record_transaction, list_user_transactions
from shared.database.base import Base
from shared.settings.service import set_tax_config


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


def _bd(subtotal="100.00", tax="18.00", total="118.00", rate="18", exempt=False, country="DO"):
    return TaxBreakdown(currency="USD", subtotal=subtotal, rate_pct=rate, tax=tax, total=total,
                        label="ITBIS", exempt=exempt, exempt_reason=None, country=country)


def _seed_user(db, uid="u1", country="DO"):
    u = User(id=uid, email=f"{uid}@x.com", password_hash="x", full_name="Cliente", country=country)
    db.add(u)
    db.commit()
    return u


def test_record_is_idempotent_by_event(db):
    _seed_user(db)
    first = record_transaction(db, user_id="u1", sku="deep_dive:banking", kind="order",
                               provider="paypal", provider_ref="ORD-1", event_id="EV1", breakdown=_bd())
    again = record_transaction(db, user_id="u1", sku="deep_dive:banking", kind="order",
                               provider="paypal", provider_ref="ORD-1", event_id="EV1", breakdown=_bd())
    assert first["id"] == again["id"]
    assert db.query(BillingTransaction).count() == 1


def test_invoice_numbers_are_sequential(db):
    _seed_user(db)
    a = record_transaction(db, user_id="u1", sku="deep_dive:banking", kind="order",
                           provider="paypal", provider_ref="O1", event_id="E1", breakdown=_bd())
    b = record_transaction(db, user_id="u1", sku="deep_dive:macro", kind="order",
                           provider="paypal", provider_ref="O2", event_id="E2", breakdown=_bd())
    assert a["invoice_number"].endswith("-00001")
    assert b["invoice_number"].endswith("-00002")


def test_persisted_breakdown_matches(db):
    _seed_user(db)
    record_transaction(db, user_id="u1", sku="insight:banking", kind="subscription",
                       provider="paypal", provider_ref="S1", event_id="E9",
                       breakdown=_bd(subtotal="50.00", tax="9.00", total="59.00"))
    row = db.query(BillingTransaction).one()
    assert str(row.subtotal) == "50.00" and str(row.tax_amount) == "9.00" and str(row.total) == "59.00"
    assert row.tax_label == "ITBIS" and row.country == "DO" and row.status == "paid"


class _Stub:
    def __init__(self, event):
        self._event = event

    def is_configured(self):
        return True

    def verify_webhook(self, *, headers, body):
        return True

    def parse_event(self, payload):
        return self._event


def test_webhook_order_records_transaction_with_tax(monkeypatch, db):
    _seed_user(db, "u1", country="DO")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", label="ITBIS", home_country="DO", exempt_foreign=True)
    ev = NormalizedEvent(event_id="W1", kind="order_paid", provider_ref="ORD-9",
                         user_id="u1", sku="deep_dive:banking", interval="once",
                         amount_gross="118.00", amount_currency="USD")
    monkeypatch.setattr(wh, "get_provider", lambda db, name: _Stub(ev))
    wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "W1"}).encode())
    tx = db.query(BillingTransaction).one()
    assert str(tx.subtotal) == "100.00" and str(tx.tax_amount) == "18.00" and str(tx.total) == "118.00"
    assert tx.kind == "order" and tx.tax_exempt is False


def test_webhook_foreign_subscription_is_exempt(monkeypatch, db):
    _seed_user(db, "u2", country="US")
    create_tariff(db, sku="insight:banking", amount="50.00", currency="USD", interval="monthly")
    set_tax_config(db, enabled=True, rate="18", home_country="DO", exempt_foreign=True)
    ev = NormalizedEvent(event_id="W2", kind="subscription_active", provider_ref="SUB-9",
                         user_id="u2", sku="insight:banking", interval="monthly")
    monkeypatch.setattr(wh, "get_provider", lambda db, name: _Stub(ev))
    wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "W2"}).encode())
    tx = db.query(BillingTransaction).one()
    assert str(tx.subtotal) == "50.00" and str(tx.tax_amount) == "0.00" and tx.tax_exempt is True


def test_webhook_duplicate_does_not_double_invoice(monkeypatch, db):
    _seed_user(db, "u1", country="DO")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    ev = NormalizedEvent(event_id="DUP", kind="order_paid", provider_ref="O",
                         user_id="u1", sku="deep_dive:banking", interval="once")
    monkeypatch.setattr(wh, "get_provider", lambda db, name: _Stub(ev))
    body = json.dumps({"id": "DUP"}).encode()
    wh.handle_webhook(db, "paypal", {}, body)
    wh.handle_webhook(db, "paypal", {}, body)
    assert db.query(BillingTransaction).count() == 1


def test_invoice_pdf_renders(db):
    u = _seed_user(db)
    tx = record_transaction(db, user_id="u1", sku="deep_dive:banking", kind="order",
                            provider="paypal", provider_ref="ORD-1", event_id="EV1", breakdown=_bd())
    row = db.query(BillingTransaction).filter_by(id=tx["id"]).one()
    from shared.billing.invoice import render_invoice_pdf
    pdf = render_invoice_pdf(db, row, u)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000


def test_my_invoices_scoped_to_user(db):
    _seed_user(db, "u1")
    _seed_user(db, "u2")
    record_transaction(db, user_id="u1", sku="deep_dive:banking", kind="order", provider="paypal",
                       provider_ref="O1", event_id="E1", breakdown=_bd())
    record_transaction(db, user_id="u2", sku="deep_dive:macro", kind="order", provider="paypal",
                       provider_ref="O2", event_id="E2", breakdown=_bd())
    assert len(list_user_transactions(db, "u1")) == 1
    assert list_user_transactions(db, "u1")[0]["user_id"] == "u1"
