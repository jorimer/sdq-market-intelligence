"""Tests del resolvedor de entitlements de la superficie comercial (shared/products/access).

Cubre la tabla de verdad de ``can_access`` (activación × tier × nivel), la traducción
a HTTP de ``enforce_access`` (404 no-publicado / 402 upsell) y la dependency
``require_product_access`` sobre una app mínima. Doctrina de la fase: Pulse = free,
Insight = pro, Deep Dive = enterprise; sin bypass de admin; orden activación→tier.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import AccessTier, User, tier_satisfies
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.access import (
    AccessOutcome,
    TIER_FOR_LEVEL,
    can_access,
    enforce_access,
    required_tier_for,
    require_product_access,
)
from shared.products.models import ProductActivation, ProductEntitlement
from shared.products.tiers import ProductTier


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, ProductActivation.__table__,
                                             ProductEntitlement.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _User:
    """Stub liviano: ``can_access`` solo lee ``.tier``."""

    def __init__(self, tier):
        self.tier = tier


def _activate(db, sector, tier, is_active=True):
    db.add(ProductActivation(sector_key=sector, tier=tier.value, is_active=is_active))
    db.commit()


# ─── Mapeo nivel → tier requerido + jerarquía de tier ──────────────────

def test_level_to_tier_mapping():
    assert TIER_FOR_LEVEL[ProductTier.pulse] is AccessTier.free
    assert TIER_FOR_LEVEL[ProductTier.insight] is AccessTier.pro
    assert TIER_FOR_LEVEL[ProductTier.deep_dive] is AccessTier.enterprise
    assert required_tier_for(ProductTier.insight) is AccessTier.pro


def test_tier_hierarchy_is_inclusive():
    # enterprise ⊇ pro ⊇ free
    assert tier_satisfies(AccessTier.enterprise, AccessTier.free)
    assert tier_satisfies(AccessTier.enterprise, AccessTier.pro)
    assert tier_satisfies(AccessTier.pro, AccessTier.free)
    assert tier_satisfies(AccessTier.free, AccessTier.free)
    # no hacia arriba
    assert not tier_satisfies(AccessTier.free, AccessTier.pro)
    assert not tier_satisfies(AccessTier.pro, AccessTier.enterprise)


# ─── Tabla de verdad de can_access ─────────────────────────────────────

def test_not_activated_is_not_published_regardless_of_tier(db):
    # Sin fila de activación: no publicado, aunque el tier sobre.
    d = can_access(db, _User(AccessTier.enterprise), "banking", ProductTier.pulse)
    assert d.outcome is AccessOutcome.not_published
    assert not d.allowed


def test_deactivated_is_not_published(db):
    _activate(db, "banking", ProductTier.pulse, is_active=False)
    d = can_access(db, _User(AccessTier.enterprise), "banking", ProductTier.pulse)
    assert d.outcome is AccessOutcome.not_published


def test_activated_and_tier_suffices_is_allowed(db):
    _activate(db, "banking", ProductTier.insight)
    d = can_access(db, _User(AccessTier.pro), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.allowed
    assert d.allowed
    # enterprise también alcanza insight (jerárquico)
    assert can_access(db, _User(AccessTier.enterprise), "banking", ProductTier.insight).allowed


def test_activated_but_tier_insufficient_requires_upgrade(db):
    _activate(db, "banking", ProductTier.deep_dive)
    d = can_access(db, _User(AccessTier.pro), "banking", ProductTier.deep_dive)
    assert d.outcome is AccessOutcome.tier_required
    assert d.required_tier is AccessTier.enterprise
    assert d.user_tier is AccessTier.pro


def test_free_user_reaches_pulse_only(db):
    for t in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
        _activate(db, "macro", t)
    free = _User(AccessTier.free)
    assert can_access(db, free, "macro", ProductTier.pulse).allowed
    assert not can_access(db, free, "macro", ProductTier.insight).allowed
    assert not can_access(db, free, "macro", ProductTier.deep_dive).allowed


def test_activation_gate_wins_over_tier(db):
    # Invariante anti-fuga del orden: sin activación, el resultado es not_published
    # AUNQUE el tier también sería insuficiente (no se filtra el "te falta plan").
    d = can_access(db, _User(AccessTier.free), "banking", ProductTier.insight)
    assert d.outcome is AccessOutcome.not_published


def test_missing_user_tier_defaults_to_free(db):
    _activate(db, "macro", ProductTier.insight)
    d = can_access(db, _User(None), "macro", ProductTier.insight)
    assert d.user_tier is AccessTier.free
    assert d.outcome is AccessOutcome.tier_required


# ─── enforce_access: traducción a HTTP ─────────────────────────────────

def test_enforce_allowed_is_noop(db):
    _activate(db, "banking", ProductTier.pulse)
    enforce_access(can_access(db, _User(AccessTier.free), "banking", ProductTier.pulse))


def test_enforce_not_published_raises_404(db):
    from fastapi import HTTPException
    d = can_access(db, _User(AccessTier.enterprise), "banking", ProductTier.pulse)
    with pytest.raises(HTTPException) as ei:
        enforce_access(d)
    assert ei.value.status_code == 404
    # No revela el motivo de tier ni la existencia del producto.
    assert "no disponible" in ei.value.detail.lower()


def test_enforce_tier_required_raises_402_with_upsell(db):
    from fastapi import HTTPException
    _activate(db, "banking", ProductTier.insight)
    d = can_access(db, _User(AccessTier.free), "banking", ProductTier.insight)
    with pytest.raises(HTTPException) as ei:
        enforce_access(d)
    assert ei.value.status_code == 402
    detail = ei.value.detail
    assert detail["required_tier"] == "pro"
    assert detail["user_tier"] == "free"
    assert detail["tier"] == "insight"


# ─── Dependency require_product_access sobre una app mínima ─────────────

def _client(db, user_tier=AccessTier.free):
    app = FastAPI()

    @app.get("/api/v1/products/{sector}/{tier}/report")
    async def _serve(decision=Depends(require_product_access)):
        return {"outcome": decision.outcome.value, "sector": decision.sector_key}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _User(user_tier)
    return TestClient(app)


def test_dependency_not_published_404(db):
    assert _client(db).get("/api/v1/products/banking/pulse/report").status_code == 404


def test_dependency_tier_required_402(db):
    _activate(db, "banking", ProductTier.insight)
    r = _client(db, AccessTier.free).get("/api/v1/products/banking/insight/report")
    assert r.status_code == 402
    assert r.json()["detail"]["required_tier"] == "pro"


def test_dependency_allowed_200(db):
    _activate(db, "banking", ProductTier.insight)
    r = _client(db, AccessTier.enterprise).get("/api/v1/products/banking/insight/report")
    assert r.status_code == 200
    assert r.json()["outcome"] == "allowed"


def test_dependency_invalid_tier_400(db):
    r = _client(db).get("/api/v1/products/banking/nope/report")
    assert r.status_code == 400


def test_dependency_requires_auth(db):
    """Sin override de usuario, la superficie comercial exige autenticación (no anónima)."""
    app = FastAPI()

    @app.get("/api/v1/products/{sector}/{tier}/report")
    async def _serve(decision=Depends(require_product_access)):
        return {"ok": True}

    app.dependency_overrides[get_db] = lambda: db
    # sin override de get_current_user → HTTPBearer exige credenciales. El código
    # exacto (401/403) depende de la versión de Starlette; lo que importa es que NO
    # es anónima (4xx de auth, nunca 200).
    r = TestClient(app).get("/api/v1/products/banking/pulse/report")
    assert r.status_code in (401, 403)
