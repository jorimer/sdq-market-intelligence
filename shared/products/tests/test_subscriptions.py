"""Tests de suscripciones (servicio + composición en can_access).

Cubre el upsert idempotente por (provider, sub_id), la validación de tier/estado, el
resolver del tier vigente (activo dentro de período vs expirado/cancelado/fuera de período,
máximo de varios), y que ``can_access`` componga la suscripción SIN pisar el tier manual ni
revelar productos no publicados.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import AccessTier
from shared.database.base import Base
from shared.products.access import AccessOutcome, can_access
from shared.products.models import ProductActivation, ProductEntitlement, Subscription
from shared.products.subscriptions import (
    SubscriptionError,
    active_subscription_tier,
    apply_subscription,
    cancel_subscription,
    expire_subscription,
    list_user_subscriptions,
    set_manual_subscription,
)
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        ProductActivation.__table__, ProductEntitlement.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _User:
    """Stub: can_access lee .tier y .id."""

    def __init__(self, tier, uid="u1"):
        self.tier = tier
        self.id = uid


def _activate(db, sector, tier):
    db.add(ProductActivation(sector_key=sector, tier=tier.value, is_active=True))
    db.commit()


def _future(days=30):
    return datetime.now(timezone.utc) + timedelta(days=days)


# ── Servicio ──────────────────────────────────────────────────────────

def test_apply_creates_and_resolves(db):
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    assert active_subscription_tier(db, "u1") == AccessTier.pro


def test_apply_is_idempotent_upsert(db):
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="cancelled", current_period_end=_future())
    rows = list_user_subscriptions(db, "u1")
    assert len(rows) == 1 and rows[0]["status"] == "cancelled"
    assert rows[0]["cancelled_at"] is not None


def test_invalid_tier_and_status_rejected(db):
    with pytest.raises(SubscriptionError):
        apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                           tier="free", status="active")
    with pytest.raises(SubscriptionError):  # tier fuera del enum
        apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S0",
                           tier="bogus", status="active")
    with pytest.raises(SubscriptionError):
        apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S2",
                           tier="pro", status="inventado")


def test_expired_or_cancelled_or_out_of_period_grants_nothing(db):
    # cancelada
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="C",
                       tier="pro", status="cancelled", current_period_end=_future())
    # activa pero fuera de período (period_end pasado)
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="P",
                       tier="enterprise", status="active",
                       current_period_end=datetime.now(timezone.utc) - timedelta(days=1))
    assert active_subscription_tier(db, "u1") is None


def test_resolver_takes_highest_active(db):
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="A",
                       tier="pro", status="active", current_period_end=_future())
    apply_subscription(db, user_id="u1", provider="azul", provider_subscription_id="B",
                       tier="enterprise", status="active", current_period_end=_future())
    assert active_subscription_tier(db, "u1") == AccessTier.enterprise


def test_open_ended_period_is_active(db):
    apply_subscription(db, user_id="u1", provider="manual", provider_subscription_id="M",
                       tier="pro", status="active", current_period_end=None)
    assert active_subscription_tier(db, "u1") == AccessTier.pro


def test_expire_cuts_access(db):
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    assert expire_subscription(db, "paypal", "S1") is True
    assert active_subscription_tier(db, "u1") is None
    assert expire_subscription(db, "paypal", "nope") is False


def test_no_user_id_returns_none(db):
    assert active_subscription_tier(db, "") is None


def test_upsert_updates_started_at_and_note(db):
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    new_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                             tier="pro", status="active", current_period_end=_future(),
                             started_at=new_start, note="renovación")
    assert out["note"] == "renovación"
    assert out["started_at"].startswith("2026-01-01")


def test_resolver_skips_row_with_invalid_tier(db):
    # Defensa: una fila con tier fuera del enum no concede acceso (se ignora).
    db.add(Subscription(user_id="u1", provider="x", provider_subscription_id="bad",
                        tier="bogus", status="active", current_period_end=_future().replace(tzinfo=None)))
    db.commit()
    assert active_subscription_tier(db, "u1") is None


# ── Composición en can_access (sin pisar el tier manual) ───────────────

def test_subscription_unlocks_insight_for_free_user(db):
    _activate(db, "banking", ProductTier.insight)
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.allowed
    # El tier manual reportado sigue siendo free (la suscripción no lo muta).
    assert d.user_tier == AccessTier.free


def test_expired_subscription_does_not_unlock(db):
    _activate(db, "banking", ProductTier.insight)
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="expired", current_period_end=_future())
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.tier_required


def test_pro_subscription_does_not_reach_deep_dive(db):
    _activate(db, "banking", ProductTier.deep_dive)
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="pro", status="active", current_period_end=_future())
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.deep_dive)
    assert d.outcome is AccessOutcome.tier_required  # deep_dive requiere enterprise


def test_subscription_never_reveals_unpublished(db):
    # No activado: aunque la suscripción alcance, sigue siendo not_published (no se revela).
    apply_subscription(db, user_id="u1", provider="paypal", provider_subscription_id="S1",
                       tier="enterprise", status="active", current_period_end=_future())
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.not_published


# ── Gestión MANUAL por admin (alta / cambio de plan / baja) ──
def test_set_manual_subscription_creates_then_upserts(db):
    a = set_manual_subscription(db, user_id="u1", tier="pro", note="lanzamiento")
    assert a["provider"] == "manual" and a["tier"] == "pro" and a["status"] == "active"
    assert active_subscription_tier(db, "u1") == AccessTier.pro
    # Cambio de plan: misma fila (una manual por usuario), tier nuevo.
    b = set_manual_subscription(db, user_id="u1", tier="enterprise")
    assert b["id"] == a["id"] and b["tier"] == "enterprise"
    assert len(list_user_subscriptions(db, "u1")) == 1
    assert active_subscription_tier(db, "u1") == AccessTier.enterprise


def test_cancel_then_reactivate(db):
    a = set_manual_subscription(db, user_id="u2", tier="pro")
    assert cancel_subscription(db, a["id"]) is True
    assert active_subscription_tier(db, "u2") is None  # baja corta el acceso
    rows = list_user_subscriptions(db, "u2")
    assert rows[0]["status"] == "cancelled" and rows[0]["cancelled_at"] is not None
    # Reactivar (set de nuevo) limpia la baja y reconcede el tier.
    b = set_manual_subscription(db, user_id="u2", tier="pro")
    assert b["id"] == a["id"] and b["status"] == "active" and b["cancelled_at"] is None
    assert active_subscription_tier(db, "u2") == AccessTier.pro


def test_cancel_unknown_returns_false(db):
    assert cancel_subscription(db, "no-existe") is False


def test_manual_rejects_free_tier(db):
    with pytest.raises(SubscriptionError):
        set_manual_subscription(db, user_id="u3", tier="free")


def test_manual_respects_period_end(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    set_manual_subscription(db, user_id="u4", tier="pro", current_period_end=past)
    assert active_subscription_tier(db, "u4") is None  # fuera de período → sin acceso
