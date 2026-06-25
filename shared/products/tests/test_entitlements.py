"""Tests del entitlement por-producto (monetización B0): el servicio, ``has_product_
entitlement`` + ``can_access`` que lo honra, y los endpoints admin de aprovisionamiento.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import AccessTier, User, UserRole, role_satisfies
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.access import AccessOutcome, can_access, has_product_entitlement
from shared.products.entitlements import (
    EntitlementError,
    grant_entitlement,
    list_user_entitlements,
    revoke_entitlement,
)
from shared.products.models import ProductActivation, ProductEntitlement, Subscription
from shared.products.router import router
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, ProductActivation.__table__,
                                             ProductEntitlement.__table__,
                                             Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _User:
    def __init__(self, tier, uid="u1"):
        self.tier = tier
        self.id = uid


def _activate(db, sector, tier):
    db.add(ProductActivation(sector_key=sector, tier=tier.value, is_active=True))
    db.commit()


def _grant_row(db, uid, sector, tier, *, active=True, expires_at=None):
    db.add(ProductEntitlement(user_id=uid, sector_key=sector, tier=tier.value,
                              active=active, expires_at=expires_at))
    db.commit()


# ─── has_product_entitlement ───────────────────────────────────────────

def test_no_entitlement_is_false(db):
    assert has_product_entitlement(db, "u1", "banking", ProductTier.insight) is False


def test_active_perpetual_entitlement_is_true(db):
    _grant_row(db, "u1", "banking", ProductTier.insight)
    assert has_product_entitlement(db, "u1", "banking", ProductTier.insight) is True


def test_revoked_entitlement_is_false(db):
    _grant_row(db, "u1", "banking", ProductTier.insight, active=False)
    assert has_product_entitlement(db, "u1", "banking", ProductTier.insight) is False


def test_expired_entitlement_is_false(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _grant_row(db, "u1", "banking", ProductTier.insight, expires_at=past)
    assert has_product_entitlement(db, "u1", "banking", ProductTier.insight) is False


def test_future_expiry_entitlement_is_true(db):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    _grant_row(db, "u1", "banking", ProductTier.insight, expires_at=future)
    assert has_product_entitlement(db, "u1", "banking", ProductTier.insight) is True


def test_entitlement_is_specific_to_sector_tier_user(db):
    _grant_row(db, "u1", "banking", ProductTier.insight)
    assert has_product_entitlement(db, "u1", "banking", ProductTier.deep_dive) is False
    assert has_product_entitlement(db, "u1", "macro", ProductTier.insight) is False
    assert has_product_entitlement(db, "u2", "banking", ProductTier.insight) is False


# ─── can_access honra el entitlement (compra) además del tier ──────────

def test_entitlement_unlocks_level_above_tier(db):
    _activate(db, "banking", ProductTier.insight)
    _grant_row(db, "u1", "banking", ProductTier.insight)
    # free no alcanza insight por tier, pero compró el producto → allowed.
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.allowed
    # otro usuario sin compra → sigue bloqueado (upsell).
    d2 = can_access(db, _User(AccessTier.free, "u2"), "banking", ProductTier.insight)
    assert d2.outcome is AccessOutcome.tier_required


def test_entitlement_does_not_reveal_unpublished(db):
    # Sin activación, ni siquiera un entitlement abre el producto (no se revela).
    _grant_row(db, "u1", "banking", ProductTier.insight)
    d = can_access(db, _User(AccessTier.free, "u1"), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.not_published


# ─── Servicio ──────────────────────────────────────────────────────────

def test_grant_and_list_and_revoke(db):
    res = grant_entitlement(db, user_id="u1", sector_key="banking", tier="deep_dive",
                            granted_by="admin1", note="pago manual #42")
    assert res["active"] is True and res["sector_key"] == "banking"
    rows = list_user_entitlements(db, "u1")
    assert len(rows) == 1 and rows[0]["note"] == "pago manual #42"
    assert revoke_entitlement(db, res["id"]) is True
    assert list_user_entitlements(db, "u1")[0]["active"] is False
    assert revoke_entitlement(db, "nope") is False


def test_grant_invalid_sector_or_tier_raises(db):
    with pytest.raises(EntitlementError):
        grant_entitlement(db, user_id="u1", sector_key="nope", tier="insight", granted_by=None)
    with pytest.raises(EntitlementError):
        grant_entitlement(db, user_id="u1", sector_key="banking", tier="nope", granted_by=None)


# ─── Endpoints admin ───────────────────────────────────────────────────

def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/products")

    class _U:
        id = "admin1"

        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)

    def _admin_dep(r=role):
        def _inner():
            u = _U(r)
            if not role_satisfies(u.role, UserRole.admin):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Se requiere rol: admin")
            return u
        return _inner

    app.dependency_overrides[require_role(UserRole.admin)] = _admin_dep()
    return TestClient(app)


def _seed_user(db, uid="target1"):
    db.add(User(id=uid, email=f"{uid}@x.com", password_hash="x", full_name="T",
                role=UserRole.viewer, tier=AccessTier.free))
    db.commit()


def test_admin_grant_list_revoke_flow(db):
    _seed_user(db, "target1")
    c = _client(db)
    r = c.post("/api/v1/products/entitlements",
               json={"user_id": "target1", "sector": "banking", "tier": "deep_dive"})
    assert r.status_code == 200
    eid = r.json()["id"]
    lst = c.get("/api/v1/products/entitlements/target1")
    assert lst.status_code == 200 and len(lst.json()["entitlements"]) == 1
    rev = c.post(f"/api/v1/products/entitlements/{eid}/revoke")
    assert rev.status_code == 200 and rev.json()["active"] is False


def test_admin_grant_unknown_user_404(db):
    c = _client(db)
    r = c.post("/api/v1/products/entitlements",
               json={"user_id": "ghost", "sector": "banking", "tier": "insight"})
    assert r.status_code == 404


def test_admin_grant_invalid_sector_400(db):
    _seed_user(db, "target1")
    c = _client(db)
    r = c.post("/api/v1/products/entitlements",
               json={"user_id": "target1", "sector": "nope", "tier": "insight"})
    assert r.status_code == 400


def test_entitlements_require_admin(db):
    c = _client(db, role=UserRole.analyst)
    assert c.get("/api/v1/products/entitlements/x").status_code == 403
    assert c.post("/api/v1/products/entitlements",
                  json={"user_id": "x", "sector": "banking", "tier": "insight"}).status_code == 403


def test_admin_revoke_unknown_404(db):
    c = _client(db)
    assert c.post("/api/v1/products/entitlements/nope/revoke").status_code == 404
