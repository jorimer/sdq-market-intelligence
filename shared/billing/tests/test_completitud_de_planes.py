"""Completitud del mapa de billing plans: la celda que falta se DECLARA, no se descubre.

**Por qué existe este archivo.** El 2026-07-13 un cliente real llegó al checkout de
``all_access`` anual y recibió un 503: no existía el billing plan de esa celda. El chequeo
de alistamiento decía verde, porque miraba ``bool(plans)`` — verdadero en cuanto UNA celda
está mapeada. Mapa completo y mapa a medias se veían idénticos, así que el hueco solo podía
aparecer en la cara del cliente que iba a pagar.

Vendible = tiene precio vigente. Un SKU de suscripción sin precio no se ofrece y no
necesita plan: contarlo como falta convertiría el chequeo en ruido permanente.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.billing.models import Tariff
from shared.billing.plan_sync import missing_plan_cells
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


def _mapear(db, plans):
    from shared.settings.service import set_paypal_config
    set_paypal_config(db, client_id="cid", secret="sec", webhook_id="wh",
                      env="live", enabled=True, plans=plans)


def _celdas(db):
    return {(c["sku"], c["interval"]) for c in missing_plan_cells(db)}


def test_sin_precio_no_es_una_falta(db):
    """Nada vendible ⇒ nada que mapear. Si esto fallara, el chequeo sería ruido eterno."""
    _mapear(db, {})
    assert missing_plan_cells(db) == []


def test_la_celda_anual_faltante_se_detecta_con_la_mensual_mapeada(db):
    """EL CASO DE PRODUCCIÓN: ``all_access`` mensual mapeado, anual no. ``bool(plans)`` era
    verdadero y el chequeo daba verde mientras el checkout anual devolvía 503."""
    create_tariff(db, sku="all_access", amount=999, interval="monthly")
    create_tariff(db, sku="all_access", amount=9990, interval="annual")
    _mapear(db, {"all_access": {"monthly": "P-MENSUAL"}})

    faltan = _celdas(db)
    assert ("all_access", "annual") in faltan, "no detectó la celda que tumbó el checkout"
    assert ("all_access", "monthly") not in faltan


def test_mapa_completo_no_reporta_faltas(db):
    create_tariff(db, sku="all_access", amount=999, interval="monthly")
    create_tariff(db, sku="all_access", amount=9990, interval="annual")
    _mapear(db, {"all_access": {"monthly": "P-M", "annual": "P-A"}})
    assert missing_plan_cells(db) == []


def test_un_plan_id_vacio_cuenta_como_falta(db):
    """Mapeado a cadena vacía es lo mismo que no mapeado: PayPal no cobra contra eso."""
    create_tariff(db, sku="all_access", amount=9990, interval="annual")
    _mapear(db, {"all_access": {"annual": "   "}})
    assert ("all_access", "annual") in _celdas(db)


def test_el_barrido_cubre_mas_de_un_sku(db):
    """Un barrido que solo mira ``all_access`` volvería a dejar celdas fuera del glob."""
    create_tariff(db, sku="all_access", amount=9990, interval="annual")
    create_tariff(db, sku="insight:banking", amount=149, interval="monthly")
    _mapear(db, {})
    faltan = _celdas(db)
    assert {("all_access", "annual"), ("insight:banking", "monthly")} <= faltan
