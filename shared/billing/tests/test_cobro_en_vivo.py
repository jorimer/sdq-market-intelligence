"""Los cuatro defectos que rompen el cobro EN VIVO y que el sandbox no puede mostrar.

El sandbox de PayPal no entrega webhooks, así que todo se validó por el retorno/captura —
que es exactamente el camino donde ninguno de estos cuatro se manifiesta:

1. la renovación de una suscripción nunca llegaba (el acceso se cortaba al mes 2);
2. sin ``webhook_id`` los eventos se rechazaban como "firma inválida", que es falso;
3. un ``special:*`` se cobraba sin dejar factura ni registro;
4. un reembolso no revertía nada ni emitía la nota de crédito que el NCF exige.
"""
import json

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
from shared.billing.fiscal.sequences import upsert_sequence
from shared.billing.fiscal.types import (
    NCF_CONSUMO,
    NCF_NOTA_CREDITO,
    REGIME_NCF,
)
from shared.billing.models import BillingTransaction
from shared.billing.providers.base import NormalizedEvent, ProviderNotConfigured
from shared.billing.providers.paypal import PayPalProvider
from shared.billing.settlement import settle_order, settle_refund, settle_renewal
from shared.billing.tariffs import create_tariff
from shared.database.base import Base
from shared.products.entitlements import list_user_entitlements
from shared.products.models import Subscription
from shared.products.subscriptions import apply_subscription

_CFG_LIVE = {"enabled": True, "client_id": "cid", "secret": "sec",
             "webhook_id": "WH-123", "env": "live", "plans": {}}


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


def _user(db, *, email="cliente@ejemplo.do", country="DO"):
    u = User(email=email, password_hash="x", full_name="Cliente", is_active=True,
             role="viewer", country=country)
    db.add(u)
    db.commit()
    return u


def _rangos(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=500)
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_NOTA_CREDITO, range_from=1, range_to=100)


# ═══ Defecto 1: las renovaciones no existían ═══════════════════════

def test_paypal_reconoce_el_cobro_recurrente():
    """``PAYMENT.SALE.COMPLETED`` con ``billing_agreement_id`` ES una renovación. Antes no se
    parseaba: el evento entraba y se descartaba como "no relevante"."""
    p = PayPalProvider(_CFG_LIVE)
    ev = p.parse_event({
        "id": "WH-EV-1", "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {"id": "SALE-9", "billing_agreement_id": "I-SUB-1",
                     "amount": {"total": "149.00", "currency": "USD"}},
    })
    assert ev is not None
    assert ev.kind == "subscription_renewed"
    assert ev.provider_ref == "I-SUB-1"     # la suscripción
    assert ev.charge_ref == "SALE-9"        # ESE cobro
    assert ev.amount_gross == "149.00"


def test_una_venta_puntual_no_se_confunde_con_una_renovacion():
    """Un sale SIN ``billing_agreement_id`` es una compra suelta, ya cubierta por
    PAYMENT.CAPTURE.COMPLETED. Tratarla como renovación inventaría una suscripción."""
    p = PayPalProvider(_CFG_LIVE)
    assert p.parse_event({
        "id": "WH-EV-2", "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {"id": "SALE-X", "amount": {"total": "450.00", "currency": "USD"}},
    }) is None


def test_la_renovacion_extiende_el_periodo(db, monkeypatch):
    """El defecto que cortaba el acceso al mes 2 mientras PayPal seguía cobrando."""
    _rangos(db)
    u = _user(db)
    vence = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    apply_subscription(db, user_id=u.id, provider="paypal",
                       provider_subscription_id="I-SUB-1", sku="insight:banking",
                       interval="monthly", tier="pro", status="active",
                       current_period_end=vence)
    create_tariff(db, sku="insight:banking", amount=Decimal("149.00"), interval="monthly")

    nuevo = datetime.now(timezone.utc) + timedelta(days=31)
    monkeypatch.setattr("shared.billing.settlement._period_end_for_renewal",
                        lambda *a, **k: (nuevo.isoformat(), "paypal"))

    resultado = settle_renewal(db, "paypal", subscription_id="I-SUB-1", charge_ref="SALE-9",
                               gross="175.82", currency="USD")
    assert resultado.startswith("renovacion_aplicada")
    sub = db.query(Subscription).filter_by(provider_subscription_id="I-SUB-1").one()
    assert sub.current_period_end > vence, "el período no avanzó: el acceso se cortaría igual"


def test_la_renovacion_emite_su_propio_comprobante(db, monkeypatch):
    """Cada cobro es una venta y necesita SU comprobante. El ``event_id`` de la factura se
    derivaba del id de la suscripción, así que el mes 2 se descartaba como duplicado."""
    _rangos(db)
    u = _user(db)
    apply_subscription(db, user_id=u.id, provider="paypal",
                       provider_subscription_id="I-SUB-1", sku="insight:banking",
                       interval="monthly", tier="pro", status="active")
    create_tariff(db, sku="insight:banking", amount=Decimal("149.00"), interval="monthly")
    monkeypatch.setattr("shared.billing.settlement._period_end_for_renewal",
                        lambda *a, **k: ((datetime.now(timezone.utc) + timedelta(days=31)).isoformat(), "paypal"))

    settle_renewal(db, "paypal", subscription_id="I-SUB-1", charge_ref="SALE-mes1")
    settle_renewal(db, "paypal", subscription_id="I-SUB-1", charge_ref="SALE-mes2")

    facturas = db.query(BillingTransaction).filter_by(kind="subscription").all()
    assert len(facturas) == 2, "el segundo mes quedó sin factura"
    numeros = sorted(f.ncf_number for f in facturas)
    assert numeros == ["B0200000001", "B0200000002"]


def test_reentregar_la_MISMA_renovacion_no_duplica(db, monkeypatch):
    """La idempotencia sigue en pie: el mismo cobro reentregado no factura dos veces."""
    _rangos(db)
    u = _user(db)
    apply_subscription(db, user_id=u.id, provider="paypal",
                       provider_subscription_id="I-SUB-1", sku="insight:banking",
                       interval="monthly", tier="pro", status="active")
    create_tariff(db, sku="insight:banking", amount=Decimal("149.00"), interval="monthly")
    monkeypatch.setattr("shared.billing.settlement._period_end_for_renewal",
                        lambda *a, **k: ((datetime.now(timezone.utc) + timedelta(days=31)).isoformat(), "paypal"))

    settle_renewal(db, "paypal", subscription_id="I-SUB-1", charge_ref="SALE-igual")
    settle_renewal(db, "paypal", subscription_id="I-SUB-1", charge_ref="SALE-igual")
    assert db.query(BillingTransaction).filter_by(kind="subscription").count() == 1


def test_una_renovacion_de_suscripcion_desconocida_no_inventa_nada(db):
    assert settle_renewal(db, "paypal", subscription_id="I-NO-EXISTE",
                          charge_ref="SALE-1") == "renovacion_sin_suscripcion"


# ═══ Defecto 2: sin webhook_id se mentía "firma inválida" ══════════

def test_sin_webhook_id_se_declara_falta_de_configuracion():
    """No es que la firma sea inválida: es que NO HAY con qué verificarla. El mensaje viejo
    mandaba a mirar la firma cuando lo que faltaba era cargar el Webhook ID."""
    p = PayPalProvider({**_CFG_LIVE, "webhook_id": ""})
    assert p.webhook_ready() is False
    with pytest.raises(ProviderNotConfigured) as e:
        p.verify_webhook(headers={}, body=b"{}")
    assert "Webhook ID" in str(e.value)


def test_el_webhook_sin_configurar_no_se_reporta_como_firma_invalida(db, monkeypatch):
    class _SinWebhook:
        name = "paypal"

        def is_configured(self):
            return True

        def verify_webhook(self, *, headers, body):
            raise ProviderNotConfigured("Falta el Webhook ID de PayPal.")

    monkeypatch.setattr(wh, "get_provider", lambda *a, **k: _SinWebhook())
    out = wh.handle_webhook(db, "paypal", {}, json.dumps({"id": "x"}).encode())
    assert out["status"] == "ignored"
    assert out["reason"] == "webhook_not_configured"


# ═══ Defecto 3: special:* cobraba sin registrar nada ═══════════════

def test_un_informe_a_medida_se_factura_aunque_no_conceda_acceso(db):
    """``settle_order`` devolvía antes de facturar cuando el SKU no mapeaba a un entitlement.
    ``special:research-custom`` tiene precio vigente en prod (US$3.500): se cobraba y no
    quedaba ni factura, ni NCF, ni registro contable."""
    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="special:research-custom", amount=Decimal("3500.00"), interval="once")

    resultado = settle_order(db, "paypal", order_id="PP-ESP-1", user_id=u.id,
                             sku="special:research-custom", gross="4130.00", currency="USD")
    assert resultado == "orden_sin_entitlement_automatico"

    tx = db.query(BillingTransaction).one()
    assert tx.sku == "special:research-custom"
    assert tx.ncf_number == "B0200000001"
    assert Decimal(str(tx.subtotal)) == Decimal("3500.00")
    # No concede acceso de catálogo — es correcto: se entrega a mano.
    assert list_user_entitlements(db, u.id) == []


def test_un_deep_dive_sigue_concediendo_su_acceso(db):
    """La cura del defecto 3 no puede haber roto el camino normal."""
    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    assert settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id,
                        sku="deep_dive:banking", gross="531.00",
                        currency="USD") == "entitlement_otorgado"
    assert len(list_user_entitlements(db, u.id)) == 1


# ═══ Defecto 4: el reembolso no revertía nada ═════════════════════

@pytest.mark.parametrize("resource,esperado", [
    ({"id": "R-1", "sale_id": "SALE-7"}, "SALE-7"),
    ({"id": "R-2", "links": [{"rel": "up", "href": "https://x/v2/payments/captures/CAP-9"}]}, "CAP-9"),
    ({"id": "R-3"}, None),   # sin referencia: no se adivina
])
def test_se_resuelve_el_cobro_original_del_reembolso(resource, esperado):
    p = PayPalProvider(_CFG_LIVE)
    ev = p.parse_event({"id": "WH-R", "event_type": "PAYMENT.CAPTURE.REFUNDED",
                        "resource": {**resource, "amount": {"value": "531.00",
                                                            "currency_code": "USD"}}})
    if esperado is None:
        assert ev is None, "sin referencia al cobro original no se puede saber qué revertir"
    else:
        assert ev is not None and ev.kind == "payment_refunded"
        assert ev.provider_ref == esperado


def test_el_reembolso_revierte_acceso_y_emite_nota_de_credito(db):
    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id, sku="deep_dive:banking",
                 gross="531.00", currency="USD")
    assert len(list_user_entitlements(db, u.id)) == 1

    resultado = settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1",
                              gross="531.00", currency="USD")
    assert resultado.startswith("reembolso_aplicado")

    original = db.query(BillingTransaction).filter_by(kind="order").one()
    assert original.status == "refunded" and original.refunded_at is not None

    nota = db.query(BillingTransaction).filter_by(kind="credit_note").one()
    assert nota.ncf_type == NCF_NOTA_CREDITO
    assert nota.ncf_number == "B0400000001"
    assert nota.credits_transaction_id == original.id
    assert Decimal(str(nota.total)) == Decimal("531.00")

    # El acceso no puede sobrevivir al dinero devuelto.
    assert [e for e in list_user_entitlements(db, u.id) if e["active"]] == []


def test_un_reembolso_reentregado_no_emite_dos_notas(db):
    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id, sku="deep_dive:banking",
                 gross="531.00", currency="USD")
    settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1", gross="531.00")
    assert settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1",
                         gross="531.00") == "reembolso_ya_aplicado"
    assert db.query(BillingTransaction).filter_by(kind="credit_note").count() == 1


def test_un_reembolso_parcial_prorratea_manteniendo_la_tasa(db):
    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id, sku="deep_dive:banking",
                 gross="531.00", currency="USD")
    settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1", gross="265.50")

    nota = db.query(BillingTransaction).filter_by(kind="credit_note").one()
    assert Decimal(str(nota.total)) == Decimal("265.50")
    # Mitad del cobro: mitad del subtotal y mitad del ITBIS, y siguen sumando el total.
    assert Decimal(str(nota.subtotal)) == Decimal("225.00")
    assert Decimal(str(nota.tax_amount)) == Decimal("40.50")
    assert Decimal(str(nota.subtotal)) + Decimal(str(nota.tax_amount)) == Decimal(str(nota.total))


def test_sin_secuencia_de_notas_el_reembolso_igual_queda_registrado(db):
    """Quedarse sin comprobantes 04 no puede hacer que un reembolso no deje rastro."""
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=10)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id, sku="deep_dive:banking",
                 gross="531.00", currency="USD")
    settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1", gross="531.00")

    nota = db.query(BillingTransaction).filter_by(kind="credit_note").one()
    assert nota.ncf_number is None
    assert nota.ncf_status == "sin_secuencia"


def test_el_reembolso_de_un_cobro_no_facturado_no_rompe(db):
    assert settle_refund(db, "paypal", charge_ref="PP-DESCONOCIDA",
                         refund_ref="REF-1") == "reembolso_sin_factura"


# ═══ El 607 con nota de crédito ═══════════════════════════════════

def test_el_607_declara_la_factura_reembolsada_Y_su_nota_de_credito(db):
    """Excluir la original dejaba la nota de crédito modificando un comprobante que la
    declaración nunca mencionó."""
    from shared.billing.fiscal.documents import build_607_rows

    _rangos(db)
    u = _user(db)
    create_tariff(db, sku="deep_dive:banking", amount=Decimal("450.00"), interval="once")
    settle_order(db, "paypal", order_id="PP-DD-1", user_id=u.id, sku="deep_dive:banking",
                 gross="531.00", currency="USD")
    settle_refund(db, "paypal", charge_ref="PP-DD-1", refund_ref="REF-1", gross="531.00")

    periodo = db.query(BillingTransaction).first().created_at.strftime("%Y-%m")
    filas = build_607_rows(db, periodo)
    assert len(filas) == 2, "la factura reembolsada también se declara"
    por_numero = {f[2]: f for f in filas}
    assert por_numero["B0200000001"][3] == "", "una factura no modifica a nadie"
    # La nota lleva a la factura que corrige en «Comprobante Modificado».
    assert por_numero["B0400000001"][3] == "B0200000001"
