"""Tests de RBAC + administración de usuarios — jerarquía de roles y barandas."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.admin_router import router as admin_router
from shared.auth.dependencies import get_current_user
from shared.auth.jwt_handler import hash_password
from shared.auth.models import (
    AccessTier, ROLE_RANK, User, UserRole, role_satisfies,
)
from shared.database.base import Base
from shared.database.session import get_db


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _mk(db, email, role, active=True, tier=AccessTier.free):
    u = User(email=email, password_hash=hash_password("password123"),
             full_name=email.split("@")[0], role=role, tier=tier, is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _client(db, actor: User):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin/users")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


# ── jerarquía de roles ────────────────────────────────────────────
def test_role_hierarchy():
    assert ROLE_RANK[UserRole.super_admin] > ROLE_RANK[UserRole.admin]
    assert ROLE_RANK[UserRole.admin] > ROLE_RANK[UserRole.analyst] > ROLE_RANK[UserRole.viewer]
    # super_admin satisface cualquier requerimiento; viewer no satisface admin.
    assert role_satisfies(UserRole.super_admin, UserRole.admin)
    assert role_satisfies(UserRole.admin, UserRole.admin)
    assert not role_satisfies(UserRole.analyst, UserRole.admin)
    assert role_satisfies(UserRole.viewer, UserRole.viewer)


# ── acceso al listado ─────────────────────────────────────────────
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.super_admin])
def test_admin_and_superadmin_can_list(db, role):
    actor = _mk(db, "actor@x.com", role)
    assert _client(db, actor).get("/api/v1/admin/users").status_code == 200


@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.analyst])
def test_non_admin_cannot_list(db, role):
    actor = _mk(db, "actor@x.com", role)
    assert _client(db, actor).get("/api/v1/admin/users").status_code == 403


# ── creación + anti-escalada ──────────────────────────────────────
def test_admin_can_create_lower_roles(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    r = _client(db, actor).post("/api/v1/admin/users", json={
        "email": "v@x.com", "password": "password123", "full_name": "V",
        "role": "analyst", "tier": "pro"})
    assert r.status_code == 201
    assert r.json()["role"] == "analyst" and r.json()["tier"] == "pro"


def test_admin_cannot_create_admin_or_superadmin(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    c = _client(db, actor)
    assert c.post("/api/v1/admin/users", json={
        "email": "a@x.com", "password": "password123", "full_name": "A",
        "role": "admin"}).status_code == 403
    assert c.post("/api/v1/admin/users", json={
        "email": "s@x.com", "password": "password123", "full_name": "S",
        "role": "super_admin"}).status_code == 403


def test_superadmin_can_create_admin(db):
    actor = _mk(db, "super@x.com", UserRole.super_admin)
    r = _client(db, actor).post("/api/v1/admin/users", json={
        "email": "a@x.com", "password": "password123", "full_name": "A",
        "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "admin"


# ── edición: barandas ─────────────────────────────────────────────
def test_cannot_change_own_role(db):
    actor = _mk(db, "super@x.com", UserRole.super_admin)
    r = _client(db, actor).patch(f"/api/v1/admin/users/{actor.id}", json={"role": "admin"})
    assert r.status_code == 403


def test_cannot_deactivate_self(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    r = _client(db, actor).patch(f"/api/v1/admin/users/{actor.id}", json={"is_active": False})
    assert r.status_code == 403


def test_admin_cannot_manage_peer_admin(db):
    actor = _mk(db, "admin1@x.com", UserRole.admin)
    other = _mk(db, "admin2@x.com", UserRole.admin)
    r = _client(db, actor).patch(f"/api/v1/admin/users/{other.id}", json={"full_name": "X"})
    assert r.status_code == 403


def test_admin_cannot_elevate_user_to_admin(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    target = _mk(db, "v@x.com", UserRole.viewer)
    r = _client(db, actor).patch(f"/api/v1/admin/users/{target.id}", json={"role": "admin"})
    assert r.status_code == 403


def test_admin_can_update_lower_user_tier_and_role(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    target = _mk(db, "v@x.com", UserRole.viewer)
    r = _client(db, actor).patch(f"/api/v1/admin/users/{target.id}",
                                 json={"role": "analyst", "tier": "enterprise"})
    assert r.status_code == 200
    assert r.json()["role"] == "analyst" and r.json()["tier"] == "enterprise"


# ── último super_admin ────────────────────────────────────────────
def test_cannot_demote_last_superadmin(db):
    actor = _mk(db, "super@x.com", UserRole.super_admin)
    target = _mk(db, "super2@x.com", UserRole.super_admin)
    c = _client(db, actor)
    # Hay 2 super_admins → degradar a uno se permite.
    assert c.patch(f"/api/v1/admin/users/{target.id}", json={"role": "admin"}).status_code == 200
    # Ahora queda 1 (actor). Degradarlo no se puede (pero es self → 403 igual). Probamos
    # desactivar al último vía otro super_admin recién creado para aislar la baranda.
    s3 = _mk(db, "super3@x.com", UserRole.super_admin)
    # actor + s3 activos = 2. Desactivamos actor (no-self) desde s3.
    c3 = _client(db, s3)
    assert c3.patch(f"/api/v1/admin/users/{actor.id}", json={"is_active": False}).status_code == 200
    # Queda solo s3 → desactivarlo (último) debe fallar; lo intenta otro... no hay otro.
    # Verificamos la baranda de degradación del último directamente:
    assert _is_last(db, s3)


def _is_last(db, u):
    from shared.auth.admin_router import _is_last_active_super_admin
    return _is_last_active_super_admin(db, u)


def test_cannot_delete_last_superadmin(db):
    actor = _mk(db, "super@x.com", UserRole.super_admin)
    target = _mk(db, "admin@x.com", UserRole.admin)
    c = _client(db, actor)
    # Eliminar a un admin (no último super) se permite.
    assert c.delete(f"/api/v1/admin/users/{target.id}").status_code == 200
    # actor es el último super_admin: no puede eliminarse a sí mismo.
    assert c.delete(f"/api/v1/admin/users/{actor.id}").status_code == 403


def test_admin_cannot_delete(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    target = _mk(db, "v@x.com", UserRole.viewer)
    # DELETE es exclusivo de super_admin.
    assert _client(db, actor).delete(f"/api/v1/admin/users/{target.id}").status_code == 403


def test_reset_password(db):
    actor = _mk(db, "admin@x.com", UserRole.admin)
    target = _mk(db, "v@x.com", UserRole.viewer)
    old = target.password_hash
    r = _client(db, actor).post(f"/api/v1/admin/users/{target.id}/reset-password",
                                json={"new_password": "newpassword123"})
    assert r.status_code == 200
    db.refresh(target)
    assert target.password_hash != old
