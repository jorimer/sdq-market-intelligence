"""Tests de la liquidación sin webhook (retorno/captura concede acceso) + idempotencia
cruzada con el webhook + tipo de e-CF."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.auth.models  # noqa: F401
import shared.billing.models  # noqa: F401
import shared.products.models  # noqa: F401
import shared.settings.models  # noqa: F401
from shared.auth.models import User
from shared.billing.models import BillingTransaction
from shared.billing.settlement import settle_order, settle_subscription
from shared.billing.tariffs import create_tariff
from shared.database.base import Base
from shared.products.access import has_product_entitlement
from shared.products.models import ProductEntitlement, Subscription
from shared.products.subscriptions import active_subscription_tier
from shared.products.tiers import ProductTier
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


def _seed(db, uid="u1", country="DO"):
    db.add(User(id=uid, email=f"{uid}@x.com", password_hash="x", full_name="Cliente", country=country))
    db.commit()


def test_order_grants_and_invoices_without_webhook(db):
    _seed(db, "u1", "DO")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    label = settle_order(db, "paypal", order_id="ORD-1", user_id="u1",
                         sku="deep_dive:banking", gross="118.00", currency="USD")
    assert label == "entitlement_otorgado"
    # Acceso concedido de inmediato (sin webhook).
    assert has_product_entitlement(db, "u1", "banking", ProductTier.deep_dive) is True
    tx = db.query(BillingTransaction).one()
    assert str(tx.total) == "118.00" and tx.encf_type == "32" and tx.encf_status == "pending"


def test_order_idempotent_capture_then_webhook(db):
    _seed(db, "u1", "DO")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    # Retorno/captura liquida; luego el webhook reconcilia el MISMO order_id.
    settle_order(db, "paypal", order_id="ORD-9", user_id="u1", sku="deep_dive:banking")
    label2 = settle_order(db, "paypal", order_id="ORD-9", user_id="u1", sku="deep_dive:banking")
    assert label2 == "orden_ya_liquidada"
    assert db.query(ProductEntitlement).count() == 1      # no dobló el acceso
    assert db.query(BillingTransaction).count() == 1      # no dobló la factura


def test_order_grants_even_if_invoice_cannot_be_built(db):
    # Sin precio ni bruto: igual concede el acceso (facturar no tumba el acceso).
    _seed(db, "u1", "DO")
    label = settle_order(db, "paypal", order_id="ORD-X", user_id="u1", sku="deep_dive:banking")
    assert label == "entitlement_otorgado"
    assert has_product_entitlement(db, "u1", "banking", ProductTier.deep_dive) is True
    assert db.query(BillingTransaction).count() == 0      # no se pudo facturar, pero hay acceso


def test_foreign_order_invoice_is_export_type_46(db):
    _seed(db, "u2", "US")
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", home_country="DO", exempt_foreign=True)
    settle_order(db, "paypal", order_id="ORD-2", user_id="u2", sku="deep_dive:banking")
    tx = db.query(BillingTransaction).one()
    assert tx.tax_exempt is True and str(tx.tax_amount) == "0.00" and tx.encf_type == "46"


def test_subscription_activates_and_invoices_without_webhook(db):
    _seed(db, "u1", "DO")
    create_tariff(db, sku="insight:banking", amount="50.00", currency="USD", interval="monthly")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    label = settle_subscription(db, "paypal", subscription_id="SUB-1", user_id="u1",
                                sku="insight:banking", interval="monthly")
    assert label == "suscripcion_activa"
    from shared.auth.models import AccessTier
    assert active_subscription_tier(db, "u1") == AccessTier.pro
    tx = db.query(BillingTransaction).one()
    assert str(tx.subtotal) == "50.00" and str(tx.tax_amount) == "9.00" and tx.kind == "subscription"


def test_client_with_rnc_gets_credito_fiscal_31(db):
    # Cliente RD con RNC/cédula → e-CF tipo 31 (crédito fiscal); sin RNC → 32 (consumo).
    from shared.auth.models import User
    db.add(User(id="rd1", email="rd1@x.com", password_hash="x", full_name="Banco",
                country="DO", tax_id="101010101"))
    db.add(User(id="rd2", email="rd2@x.com", password_hash="x", full_name="Consumidor",
                country="DO", tax_id=None))
    db.commit()
    create_tariff(db, sku="deep_dive:banking", amount="100.00", currency="USD", interval="once")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    settle_order(db, "paypal", order_id="O-RNC", user_id="rd1", sku="deep_dive:banking")
    settle_order(db, "paypal", order_id="O-NO", user_id="rd2", sku="deep_dive:banking")
    by_user = {t.user_id: t.encf_type for t in db.query(BillingTransaction).all()}
    assert by_user["rd1"] == "31" and by_user["rd2"] == "32"


def test_subscription_idempotent_across_paths(db):
    _seed(db, "u1", "DO")
    create_tariff(db, sku="insight:banking", amount="50.00", currency="USD", interval="monthly")
    set_tax_config(db, enabled=True, rate="18", home_country="DO")
    settle_subscription(db, "paypal", subscription_id="SUB-9", user_id="u1",
                        sku="insight:banking", interval="monthly")
    settle_subscription(db, "paypal", subscription_id="SUB-9", user_id="u1",
                        sku="insight:banking", interval="monthly")
    assert db.query(Subscription).count() == 1            # upsert, no duplica
    assert db.query(BillingTransaction).count() == 1      # no dobló la factura
