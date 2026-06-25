"""Tests de la API del tarifario (/api/v1/billing).

Gating jerárquico (admin publica/lista/retira; viewer 403), publicación con validación
(400 en SKU/moneda/monto inválidos), y consulta de precio vigente (200 / 404 sin tarifa).
El ``require_role`` real corre con el ``get_current_user`` override (igual que producción).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.billing.models import Tariff
from shared.billing.router import router
from shared.database.base import Base
from shared.database.session import get_db


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


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/billing")

    class _U:
        id = "admin-1"

        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def test_admin_publishes_and_lists(db):
    c = _client(db)
    r = c.post("/api/v1/billing/tariffs", json={"sku": "insight", "amount": "299.00"})
    assert r.status_code == 200, r.text
    assert r.json()["is_current"] is True
    listing = c.get("/api/v1/billing/tariffs").json()["tariffs"]
    assert len(listing) == 1 and listing[0]["sku"] == "insight"


def test_viewer_cannot_publish(db):
    c = _client(db, role=UserRole.viewer)
    r = c.post("/api/v1/billing/tariffs", json={"sku": "insight", "amount": "299"})
    assert r.status_code == 403


def test_viewer_cannot_list(db):
    c = _client(db, role=UserRole.viewer)
    assert c.get("/api/v1/billing/tariffs").status_code == 403


def test_publish_rejects_bad_sku(db):
    c = _client(db)
    r = c.post("/api/v1/billing/tariffs", json={"sku": "deep_dive:nope", "amount": "10"})
    assert r.status_code == 400


def test_price_endpoint_returns_current(db):
    c = _client(db)
    c.post("/api/v1/billing/tariffs", json={"sku": "deep_dive:banking", "amount": "199"})
    r = c.get("/api/v1/billing/tariffs/price/deep_dive:banking")
    assert r.status_code == 200
    assert r.json()["amount"] == "199.00"


def test_price_endpoint_404_without_tariff(db):
    c = _client(db)
    assert c.get("/api/v1/billing/tariffs/price/insight").status_code == 404


def test_price_endpoint_open_to_any_authenticated(db):
    # Un viewer SÍ puede consultar el precio (alimenta el catálogo), aunque no administre.
    admin = _client(db)
    admin.post("/api/v1/billing/tariffs", json={"sku": "insight", "amount": "299"})
    viewer = _client(db, role=UserRole.viewer)
    assert viewer.get("/api/v1/billing/tariffs/price/insight").status_code == 200


def test_withdraw_then_404(db):
    c = _client(db)
    tid = c.post("/api/v1/billing/tariffs", json={"sku": "insight", "amount": "299"}).json()["id"]
    assert c.post(f"/api/v1/billing/tariffs/{tid}/withdraw").status_code == 200
    assert c.get("/api/v1/billing/tariffs/price/insight").status_code == 404


def test_withdraw_missing_404(db):
    c = _client(db)
    assert c.post("/api/v1/billing/tariffs/nope/withdraw").status_code == 404
