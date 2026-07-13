"""Tests del flujo de auth con cookies httpOnly (brecha 2 del DD).

Cubre: login setea cookies httpOnly; /me autentica por cookie SIN header; el header
Bearer sigue funcionando (clientes de API); refresh vía cookie y vía body; logout
borra las cookies; y sin ninguna fuente → 401 (no 403).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.jwt_handler import hash_password
from shared.auth.models import User, UserRole
from shared.auth.router import router as auth_router
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


@pytest.fixture()
def client(db):
    db.add(User(email="ana@x.do", password_hash=hash_password("secreto123"),
                full_name="Ana", role=UserRole.viewer))
    db.commit()
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _login(client) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": "ana@x.do", "password": "secreto123"})
    assert r.status_code == 200
    return r.json()


def test_login_setea_cookies_httponly(client):
    r = client.post("/api/v1/auth/login", json={"email": "ana@x.do", "password": "secreto123"})
    assert r.status_code == 200
    set_cookies = ";".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookies and "refresh_token=" in set_cookies
    assert "HttpOnly" in set_cookies
    assert "SameSite=lax" in set_cookies or "samesite=lax" in set_cookies.lower()
    # el refresh token solo viaja al path de auth
    assert "Path=/api/v1/auth" in set_cookies
    # los tokens siguen en el body (clientes de API por Bearer)
    body = r.json()
    assert body["access_token"] and body["refresh_token"]


def test_me_autentica_por_cookie_sin_header(client):
    _login(client)  # TestClient conserva las cookies de la sesión
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "ana@x.do"


def test_me_autentica_por_bearer_sin_cookie(client):
    body = _login(client)
    client.cookies.clear()
    r = client.get("/api/v1/auth/me",
                   headers={"Authorization": f"Bearer {body['access_token']}"})
    assert r.status_code == 200


def test_sin_fuente_da_401(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401  # antes HTTPBearer(auto_error=True) devolvía 403


def test_refresh_via_cookie_body_vacio(client):
    _login(client)
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert "access_token=" in ";".join(r.headers.get_list("set-cookie"))


def test_refresh_via_body_sin_cookie(client):
    body = _login(client)
    client.cookies.clear()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200


def test_refresh_sin_nada_da_401(client):
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401


def test_refresh_con_access_token_en_body_da_401(client):
    body = _login(client)
    client.cookies.clear()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": body["access_token"]})
    assert r.status_code == 401  # type != refresh


def test_logout_borra_cookies(client):
    _login(client)
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    expired = ";".join(r.headers.get_list("set-cookie"))
    assert 'access_token="";' in expired or "access_token=;" in expired.replace('""', "")
    # tras el logout, la cookie ya no autentica
    r2 = client.get("/api/v1/auth/me")
    assert r2.status_code == 401
