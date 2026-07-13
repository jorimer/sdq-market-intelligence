"""Tests del sync automático tarifario → billing plans de PayPal (plan_sync)."""
from typing import Dict, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.billing.models import Tariff
from shared.billing.plan_sync import sync_paypal_plans
from shared.billing.providers.base import ProviderError
from shared.billing.tariffs import create_tariff
from shared.database.base import Base
from shared.settings.models import AppSetting


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Tariff.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class FakeProvider:
    """Doble del PayPalProvider: registra llamadas y simula el estado remoto."""

    def __init__(self, *, enabled: bool = True,
                 remote_plans: Optional[Dict[str, dict]] = None):
        self.enabled = enabled
        self.remote_plans = remote_plans or {}
        self.created_products: List[str] = []
        self.created_plans: List[dict] = []
        self.deactivated: List[str] = []
        self._seq = 0

    def is_configured(self) -> bool:
        return self.enabled

    def get_plan(self, plan_id: str) -> dict:
        if plan_id not in self.remote_plans:
            raise ProviderError("RESOURCE_NOT_FOUND")
        return self.remote_plans[plan_id]

    def create_product(self, *, name: str, description: str = "") -> str:
        self._seq += 1
        pid = f"PROD-{self._seq}"
        self.created_products.append(name)
        return pid

    def create_plan(self, *, product_id: str, name: str, interval: str,
                    amount: str, currency: str) -> str:
        self._seq += 1
        plan_id = f"P-{self._seq}"
        self.created_plans.append({"id": plan_id, "product_id": product_id,
                                   "interval": interval, "amount": amount,
                                   "currency": currency})
        self.remote_plans[plan_id] = {"id": plan_id, "status": "ACTIVE",
                                      "value": amount, "currency_code": currency,
                                      "product_id": product_id}
        return plan_id

    def deactivate_plan(self, plan_id: str) -> None:
        self.deactivated.append(plan_id)
        if plan_id in self.remote_plans:
            self.remote_plans[plan_id]["status"] = "INACTIVE"


def _enable_paypal(db, plans: Optional[dict] = None):
    from shared.settings.service import set_paypal_config
    set_paypal_config(db, client_id="cid", secret="sec", webhook_id="wh",
                      env="sandbox", enabled=True, plans=plans or {})


def _by_key(result):
    return {(r["sku"], r["interval"]): r for r in result["results"]}


def test_sin_pasarela_no_hace_nada(db):
    fake = FakeProvider(enabled=False)
    out = sync_paypal_plans(db, provider=fake)
    assert out == {"enabled": False, "results": [], "plans": {}}
    assert fake.created_plans == []


def test_sku_sin_precio_se_salta(db):
    _enable_paypal(db)
    fake = FakeProvider()
    out = sync_paypal_plans(db, provider=fake)
    assert out["enabled"] is True
    assert all(r["action"] == "sin_precio" for r in out["results"])
    assert fake.created_plans == []


def test_crea_plan_y_producto_para_precio_nuevo(db):
    _enable_paypal(db)
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    fake = FakeProvider()
    out = sync_paypal_plans(db, provider=fake)

    r = _by_key(out)[("insight:banking", "monthly")]
    assert r["action"] == "created"
    assert r["amount"] == "149.00"
    assert len(fake.created_products) == 1  # un Product por SKU
    assert fake.created_plans[0]["interval"] == "monthly"
    assert out["plans"]["insight:banking"]["monthly"] == r["plan_id"]

    # persistido en la config: el checkout de suscripción lo encuentra
    from shared.settings.service import get_paypal_config
    assert get_paypal_config(db)["plans"]["insight:banking"]["monthly"] == r["plan_id"]


def test_idempotente_segunda_corrida_todo_ok(db):
    _enable_paypal(db)
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    fake = FakeProvider()
    sync_paypal_plans(db, provider=fake)
    out2 = sync_paypal_plans(db, provider=fake)
    assert _by_key(out2)[("insight:banking", "monthly")]["action"] == "ok"
    assert len(fake.created_plans) == 1  # no duplica


def test_cambio_de_precio_rota_el_plan_y_desactiva_el_viejo(db):
    _enable_paypal(db)
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    fake = FakeProvider()
    first = sync_paypal_plans(db, provider=fake)
    old_id = _by_key(first)[("insight:banking", "monthly")]["plan_id"]

    create_tariff(db, sku="insight:banking", amount=199, interval="monthly")
    out = sync_paypal_plans(db, provider=fake)
    r = _by_key(out)[("insight:banking", "monthly")]
    assert r["action"] == "created" and r["amount"] == "199.00"
    assert r["replaced"] == old_id
    assert fake.deactivated == [old_id]
    # reutiliza el Product (no crea otro)
    assert len(fake.created_products) == 1


def test_plan_mapeado_roto_se_rota_sin_abortar(db):
    _enable_paypal(db, plans={"insight:banking": {"monthly": "P-ROTO"}})
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    fake = FakeProvider()  # P-ROTO no existe remotamente → get_plan lanza
    out = sync_paypal_plans(db, provider=fake)
    r = _by_key(out)[("insight:banking", "monthly")]
    assert r["action"] == "created"
    # el viejo roto se intentó desactivar best-effort (no debe romper el sync)
    assert "P-ROTO" in fake.deactivated


def test_error_de_paypal_en_un_sku_no_aborta_el_resto(db):
    _enable_paypal(db)
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    create_tariff(db, sku="all_access", amount=690, interval="monthly")

    class Flaky(FakeProvider):
        def create_plan(self, **kw):
            if "Banking" in kw["name"]:
                raise ProviderError("boom")
            return super().create_plan(**kw)

    fake = Flaky()
    out = sync_paypal_plans(db, provider=fake)
    by = _by_key(out)
    assert by[("insight:banking", "monthly")]["action"] == "error"
    assert by[("all_access", "monthly")]["action"] == "created"


def test_deep_dive_queda_fuera(db):
    _enable_paypal(db)
    create_tariff(db, sku="deep_dive:banking", amount=450, interval="once")
    fake = FakeProvider()
    out = sync_paypal_plans(db, provider=fake)
    assert ("deep_dive:banking", "once") not in _by_key(out)
    assert fake.created_plans == []
