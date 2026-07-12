"""Test del empaquetado (Fase 6): el precio vive en el tarifario, inactivo sin tarifa."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.billing.models import Tariff
from shared.billing.tariffs import TariffError
from shared.database.base import Base
from shared.research.packaging import (
    RESEARCH_CUSTOM_SKU,
    packaging_status,
    set_provisional_price,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Tariff.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_sku_is_a_special_slug():
    assert RESEARCH_CUSTOM_SKU == "special:research-custom"


def test_inactive_without_tariff(db):
    st = packaging_status(db)
    assert st["enabled"] is False
    assert st["price_usd"] is None
    assert st["positioned_between"] == ["dd_express", "dd_full"]


def test_set_provisional_price_activates_via_tariff(db):
    set_provisional_price(db, 3500.0)
    st = packaging_status(db)
    assert st["enabled"] is True
    assert st["price_usd"] == 3500.0
    assert st["currency"] == "USD"
    assert "provisional" in st["note"].lower()


def test_price_must_be_positive(db):
    # La guarda vive en el tarifario (create_tariff); no se activa con precio inválido.
    with pytest.raises((TariffError, ValueError)):
        set_provisional_price(db, 0)
