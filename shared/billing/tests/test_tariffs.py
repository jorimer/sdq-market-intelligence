"""Tests del servicio del tarifario (shared/billing/tariffs).

Cubre publicación con validación, la semántica de vigencia por fechas (precio vigente /
programado a futuro / expirado / reemplazo por effective_from más reciente), retiro sin
borrar histórico, y la normalización UTC-naive (parity SQLite↔Postgres).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.billing.models import Tariff
from shared.billing.tariffs import (
    TariffError,
    create_tariff,
    list_tariffs,
    price_for,
    withdraw_tariff,
)
from shared.database.base import Base


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


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def test_create_and_resolve_current_price(db):
    out = create_tariff(db, sku="insight", amount="299.00")
    assert out["sku"] == "insight"
    assert out["amount"] == "299.00"
    assert out["is_current"] is True
    row = price_for(db, "insight")
    assert row is not None and row.amount == Decimal("299.00")


def test_amount_keeps_cents(db):
    create_tariff(db, sku="insight", amount=199.9)
    assert price_for(db, "insight").amount == Decimal("199.90")


def test_invalid_sku_rejected(db):
    with pytest.raises(TariffError):
        create_tariff(db, sku="deep_dive:no_existe", amount="10")


def test_invalid_currency_rejected(db):
    with pytest.raises(TariffError):
        create_tariff(db, sku="insight", amount="10", currency="DOLLARS")


def test_non_positive_amount_rejected(db):
    for bad in ["0", "-5", "abc"]:
        with pytest.raises(TariffError):
            create_tariff(db, sku="insight", amount=bad)


def test_window_end_must_follow_start(db):
    now = datetime.now(timezone.utc)
    with pytest.raises(TariffError):
        create_tariff(db, sku="insight", amount="10",
                      effective_from=now, effective_to=now - timedelta(days=1))


def test_scheduled_future_price_not_yet_current(db):
    future = datetime.now(timezone.utc) + timedelta(days=5)
    out = create_tariff(db, sku="insight", amount="350", effective_from=future)
    assert out["scheduled"] is True and out["is_current"] is False
    # No hay precio vigente ahora (solo el programado a futuro).
    assert price_for(db, "insight") is None


def test_expired_price_not_resolved(db):
    now = datetime.now(timezone.utc)
    create_tariff(db, sku="insight", amount="299",
                  effective_from=now - timedelta(days=10),
                  effective_to=now - timedelta(days=1))
    assert price_for(db, "insight") is None


def test_replacement_picks_latest_effective_from(db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    create_tariff(db, sku="insight", amount="299",
                  effective_from=now - timedelta(days=10))  # abierto
    create_tariff(db, sku="insight", amount="349",
                  effective_from=now + timedelta(days=5))   # programado
    # Hoy rige el viejo; tras la fecha programada, rige el nuevo.
    assert price_for(db, "insight", at=now).amount == Decimal("299")
    assert price_for(db, "insight", at=now + timedelta(days=6)).amount == Decimal("349")


def test_withdraw_excludes_from_resolution(db):
    out = create_tariff(db, sku="insight", amount="299")
    assert withdraw_tariff(db, out["id"]) is True
    assert price_for(db, "insight") is None
    # Sigue en el histórico (no se borra).
    assert any(t["id"] == out["id"] for t in list_tariffs(db, include_inactive=True))
    assert not list_tariffs(db, include_inactive=False)


def test_withdraw_missing_returns_false(db):
    assert withdraw_tariff(db, "nope") is False


def test_list_filters_by_sku(db):
    create_tariff(db, sku="insight", amount="299")
    create_tariff(db, sku="deep_dive:banking", amount="199")
    only = list_tariffs(db, sku="deep_dive:banking")
    assert [t["sku"] for t in only] == ["deep_dive:banking"]


def test_aware_datetime_normalized_to_naive(db):
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    create_tariff(db, sku="insight", amount="10", effective_from=aware)
    stored = db.query(Tariff).filter_by(sku="insight").one()
    assert stored.effective_from.tzinfo is None
    assert stored.effective_from == _naive(aware)
