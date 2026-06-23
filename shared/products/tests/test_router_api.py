"""Tests de la API del monitor de productos (/api/v1/products) + recálculo por evento."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.router import router
from shared.products.tiers import ProductTier
from modules.banking_score.models.models import Bank, RatingResult  # noqa: F401 — tablas


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, ProductReadiness.__table__, ProductActivation.__table__,
        Bank.__table__, RatingResult.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/products")

    class _U:
        id = "u1"

        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    # require_role(...) devuelve una nueva dependencia por llamada; sobreescribimos por
    # rol efectivo evaluando la jerarquía igual que producción.
    from shared.auth.models import role_satisfies

    def _admin_dep(r=role):
        def _inner():
            u = _U(r)
            if not role_satisfies(u.role, UserRole.admin):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Se requiere rol: admin")
            return u
        return _inner

    # Sobrescribir la dependencia concreta que usa el router (require_role(admin)).
    app.dependency_overrides[require_role(UserRole.admin)] = _admin_dep()
    return TestClient(app)


def _seed(db, sector, tier, readiness):
    db.add(ProductReadiness(sector_key=sector, tier=tier.value, readiness=readiness,
                            g1=readiness, g2=readiness, g3=readiness, g4=readiness, g5=readiness))
    db.commit()


def test_get_readiness_matrix(db):
    c = _client(db)
    r = c.get("/api/v1/products/readiness")
    assert r.status_code == 200
    assert len(r.json()["sectors"]) == 10


def test_get_sector_detail_and_404(db):
    c = _client(db)
    assert c.get("/api/v1/products/readiness/banking").status_code == 200
    assert c.get("/api/v1/products/readiness/nope").status_code == 404


def test_activate_below_threshold_409(db):
    _seed(db, "banking", ProductTier.insight, 0.80)  # < 0.85
    c = _client(db)
    r = c.post("/api/v1/products/banking/insight/activate")
    assert r.status_code == 409
    assert "umbral" in r.json()["detail"]


def test_activate_ok_and_deactivate(db):
    _seed(db, "banking", ProductTier.pulse, 0.80)  # ≥ 0.75
    c = _client(db)
    assert c.post("/api/v1/products/banking/pulse/activate").json()["is_active"] is True
    assert c.post("/api/v1/products/banking/pulse/deactivate").json()["is_active"] is False


def test_invalid_tier_400(db):
    c = _client(db)
    assert c.post("/api/v1/products/banking/nope/activate").status_code == 400


def test_recompute_requires_admin(db):
    c = _client(db, role=UserRole.analyst)
    assert c.post("/api/v1/products/readiness/recompute").status_code == 403


def test_recompute_admin_ok(db):
    import modules.banking_score.products  # noqa: F401 — registra banking
    c = _client(db)
    r = c.post("/api/v1/products/readiness/recompute")
    assert r.status_code == 200
    assert r.json()["recomputed"] == 30


def test_event_recompute_refreshes(db, monkeypatch):
    """Un evento *.updated dispara el recálculo (con la sesión de test)."""
    import shared.products.events as ev
    monkeypatch.setattr(ev, "SessionLocal", lambda: db)
    import modules.banking_score.products  # noqa: F401
    ev._on_data_updated({"any": "payload"})
    assert db.query(ProductReadiness).count() == 30


def test_manual_recompute_operation(db, monkeypatch):
    """La operación de consola (recálculo manual) corre el recompute."""
    import shared.products.operations as ops
    monkeypatch.setattr(ops, "SessionLocal", lambda: db)
    import modules.banking_score.products  # noqa: F401
    res = ops._run_recompute(params={}, user_id=None, set_phase=lambda *_: None)
    assert res["recomputed"] == 30
    assert db.query(ProductReadiness).count() == 30
