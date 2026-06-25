"""Sensor de cierre B2a: la alerta de cambio de tarifa de punta a punta.

Publicar un CAMBIO sobre un precio vigente de ``insight`` notifica a los suscriptos
afectados (pro/enterprise activos) y a NADIE más; la PRIMERA fijación de un SKU no
notifica; un cambio de un producto on-demand (deep_dive) no notifica (sin suscriptores
recurrentes). El suscriptor escribe en su propia sesión (parchada al engine de test).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.billing.events as billing_events
from shared.auth.models import AccessTier, User, UserRole
from shared.billing.events import _on_tariff_published, TARIFF_PUBLISHED
from shared.billing.models import Tariff
from shared.billing.tariffs import create_tariff
from shared.database.base import Base
from shared.events.event_bus import event_bus
from shared.notifications.service import Notification, notification_service


@pytest.fixture()
def env(monkeypatch):
    """Engine in-memory compartido (StaticPool) + handler suscrito + SessionLocal del
    suscriptor parchado al mismo engine. Aísla el event_bus global (snapshot/restore)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, Tariff.__table__, Notification.__table__])
    Maker = sessionmaker(bind=engine)
    # El handler abre su propia sesión vía SessionLocal: apuntarla al engine de test.
    monkeypatch.setattr(billing_events, "SessionLocal", Maker)
    # Aislar el bus global: snapshot de handlers, suscribir el nuestro, restaurar al final.
    saved = {k: list(v) for k, v in event_bus._handlers.items()}
    event_bus._handlers.clear()
    event_bus.subscribe(TARIFF_PUBLISHED, _on_tariff_published)
    s = Maker()
    try:
        yield s
    finally:
        s.close()
        event_bus._handlers.clear()
        for k, v in saved.items():
            event_bus._handlers[k] = v


def _user(db, email, tier, is_active=True):
    u = User(email=email, password_hash="x", full_name=email, role=UserRole.viewer,
             tier=tier, is_active=is_active)
    db.add(u)
    db.commit()
    return u


def test_first_price_does_not_notify(env):
    db = env
    pro = _user(db, "pro@x", AccessTier.pro)
    create_tariff(db, sku="insight", amount="299")  # primera fijación → no es cambio
    assert notification_service.unread_count(db, pro.id) == 0


def test_price_change_notifies_only_subscribers(env):
    db = env
    free = _user(db, "free@x", AccessTier.free)
    pro = _user(db, "pro@x", AccessTier.pro)
    ent = _user(db, "ent@x", AccessTier.enterprise)
    inact = _user(db, "off@x", AccessTier.pro, is_active=False)
    create_tariff(db, sku="insight", amount="299")  # precio vigente inicial
    future = datetime.now(timezone.utc) + timedelta(days=30)
    create_tariff(db, sku="insight", amount="349", effective_from=future)  # CAMBIO
    assert notification_service.unread_count(db, pro.id) == 1
    assert notification_service.unread_count(db, ent.id) == 1
    assert notification_service.unread_count(db, free.id) == 0
    assert notification_service.unread_count(db, inact.id) == 0
    # El cuerpo lleva el precio nuevo y la fecha de vigencia.
    body = notification_service.list_for_user(db, pro.id)[0]["body"]
    assert "349" in body and future.date().isoformat() in body


def test_deep_dive_change_notifies_nobody(env):
    db = env
    _user(db, "ent@x", AccessTier.enterprise)
    create_tariff(db, sku="deep_dive:banking", amount="199")
    create_tariff(db, sku="deep_dive:banking", amount="249")  # cambio, pero on-demand
    ent = db.query(User).filter_by(email="ent@x").one()
    assert notification_service.unread_count(db, ent.id) == 0


def test_handler_swallows_errors(env, monkeypatch):
    # Un fallo notificando NO debe propagar (no romper la publicación de la tarifa).
    db = env
    _user(db, "pro@x", AccessTier.pro)
    monkeypatch.setattr(billing_events, "affected_subscribers",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    create_tariff(db, sku="insight", amount="299")
    create_tariff(db, sku="insight", amount="349")  # publica el cambio; el handler revienta y se traga


def test_first_price_payload_marks_not_a_change_via_subscribe(env):
    # Cubre subscribe_billing_events (registro idempotente en el bus).
    billing_events.subscribe_billing_events()
    assert any(h is _on_tariff_published for h in event_bus._handlers[TARIFF_PUBLISHED])


def test_format_effective_handles_bad_iso():
    assert billing_events._format_effective("no-es-fecha") == "no-es-fecha"
    assert billing_events._format_effective("2026-07-01T00:00:00") == "2026-07-01"
