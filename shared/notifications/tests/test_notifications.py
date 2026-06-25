"""Tests del buzón de notificaciones (servicio persistido + API).

Cubre crear/listar/contar-no-leídas/marcar-leído y el aislamiento por usuario (cada uno
ve y marca SOLO lo suyo; marcar una notificación ajena no la revela → 404).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.database.base import Base
from shared.database.session import get_db
from shared.notifications.router import router
from shared.notifications.service import Notification, notification_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Notification.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


# ── Servicio ──────────────────────────────────────────────────────────

def test_create_persists_and_lists(db):
    notification_service.create(db, user_id="u1", type="info", title="Hola", body="cuerpo")
    items = notification_service.list_for_user(db, "u1")
    assert len(items) == 1
    assert items[0]["title"] == "Hola" and items[0]["read"] is False


def test_unread_count_and_filter(db):
    for i in range(3):
        notification_service.create(db, user_id="u1", type="info", title=f"n{i}")
    assert notification_service.unread_count(db, "u1") == 3
    assert len(notification_service.list_for_user(db, "u1", unread_only=True)) == 3


def test_mark_read_only_own(db):
    n = notification_service.create(db, user_id="u1", type="info", title="mía")
    # Otro usuario no puede marcarla (no es suya).
    assert notification_service.mark_read(db, "u2", n.id) is False
    assert notification_service.mark_read(db, "u1", n.id) is True
    assert notification_service.unread_count(db, "u1") == 0


def test_mark_all_read(db):
    for i in range(2):
        notification_service.create(db, user_id="u1", type="info", title=f"n{i}")
    notification_service.create(db, user_id="u2", type="info", title="ajena")
    assert notification_service.mark_all_read(db, "u1") == 2
    assert notification_service.unread_count(db, "u1") == 0
    assert notification_service.unread_count(db, "u2") == 1  # intacta


def test_list_isolated_per_user(db):
    notification_service.create(db, user_id="u1", type="info", title="mía")
    assert notification_service.list_for_user(db, "u2") == []


# ── API ───────────────────────────────────────────────────────────────

def _client(db, user_id="u1"):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/notifications")

    class _U:
        def __init__(self, uid):
            self.id = uid

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(user_id)
    return TestClient(app)


def test_api_list_and_unread(db):
    notification_service.create(db, user_id="u1", type="info", title="Hola")
    r = _client(db).get("/api/v1/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["unread"] == 1 and len(body["notifications"]) == 1


def test_api_mark_read_and_404(db):
    n = notification_service.create(db, user_id="u1", type="info", title="Hola")
    c = _client(db)
    assert c.post(f"/api/v1/notifications/{n.id}/read").status_code == 200
    assert c.get("/api/v1/notifications/unread-count").json()["unread"] == 0
    # Marcar una inexistente / ajena → 404.
    assert _client(db, user_id="u2").post(f"/api/v1/notifications/{n.id}/read").status_code == 404


def test_api_read_all(db):
    for i in range(2):
        notification_service.create(db, user_id="u1", type="info", title=f"n{i}")
    assert _client(db).post("/api/v1/notifications/read-all").json()["updated"] == 2


def test_send_compat_does_not_persist(db):
    # `send` es el compat de solo-log (sin sesión): no persiste nada.
    notification_service.send(user_id="u1", type="info", title="solo log", body="x")
    assert notification_service.list_for_user(db, "u1") == []
