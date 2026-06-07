"""Tests for the in-app settings + sector data-source config service and API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.settings import service
from shared.settings.crypto import decrypt, encrypt
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.router import router as settings_router
from shared.settings.schemas import (
    MASK,
    SectorApiIn,
    SettingsIn,
    TestConnectionIn as ConnTestIn,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection so TestClient's thread sees the tables
    )
    Base.metadata.create_all(engine, tables=[AppSetting.__table__, SectorApiConfig.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── crypto ────────────────────────────────────────────────────────
def test_crypto_roundtrip():
    assert decrypt(encrypt("super-secret-key")) == "super-secret-key"


def test_crypto_empty_and_bad():
    assert encrypt("") == ""
    assert decrypt("") == ""
    assert decrypt("not-a-valid-token") == ""  # never raises


def test_ciphertext_is_not_plaintext():
    assert "super-secret" not in encrypt("super-secret")


# ── service: claude key ───────────────────────────────────────────
def test_claude_key_stored_encrypted(db):
    service.update_settings(db, SettingsIn(claudeApiKey="sk-ant-123"))
    row = db.query(AppSetting).filter(AppSetting.key == "claude_api_key").first()
    assert row is not None
    assert row.value != "sk-ant-123"  # encrypted at rest
    assert service.get_claude_api_key(db) == "sk-ant-123"
    out = service.get_settings(db)
    assert out.claudeApiKeySet is True


# ── service: sector apis ──────────────────────────────────────────
def test_sector_api_upsert_and_masking(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", providerName="SB", apiKey="primary-key", baseUrl="https://x"),
    ]))
    out = service.get_settings(db)
    assert len(out.sectorApis) == 1
    api = out.sectorApis[0]
    assert api.provider == "sb_do"
    assert api.apiKeySet is True
    assert api.apiKeyMasked == MASK
    # The plaintext key is never returned by the API model.
    assert "primary-key" not in api.model_dump_json()


def test_masked_key_preserved_on_update(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="real-key"),
    ]))
    # Re-save sending the mask (as the UI does) → key must be kept.
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey=MASK, providerName="Updated"),
    ]))
    assert service.get_sector_api_key(db, "sb_do") == "real-key"
    assert service.get_settings(db).sectorApis[0].providerName == "Updated"


def test_empty_string_clears_key(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="k")]))
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="")]))
    assert service.get_sector_api_key(db, "sb_do") == ""


def test_resolution_helpers(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="k1", apiKeySecondary="k2",
                    baseUrl="https://apis.sb.gob.do/estadisticas/v2",
                    proxyUrl="https://w.workers.dev", proxySecret="psecret"),
    ]))
    assert service.get_sector_api_key(db, "sb_do") == "k1"
    assert service.get_sector_api_key_secondary(db, "sb_do") == "k2"
    assert service.get_sector_api_base_url(db, "sb_do").endswith("/estadisticas/v2")
    assert service.get_sector_api_proxy(db, "sb_do") == ("https://w.workers.dev", "psecret")


def test_disabled_provider_hides_key(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="k1", enabled=False),
    ]))
    # Disabled → resolution falls back (env empty here) instead of returning the key.
    assert service.get_sector_api_key(db, "sb_do") == ""


def test_delete_sector_api(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="k")]))
    assert service.delete_sector_api(db, "sb_do") is True
    assert service.delete_sector_api(db, "sb_do") is False


def test_connection_test_requires_key(db):
    res = service.test_connection(db, ConnTestIn(provider="sb_do", baseUrl="https://x", apiKey=""))
    assert res.status == "error"


# ── router RBAC ───────────────────────────────────────────────────
def _client(db, role):
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/v1/settings")

    class _U:
        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def test_admin_can_read(db):
    r = _client(db, UserRole.admin).get("/api/v1/settings")
    assert r.status_code == 200
    assert "sectorApis" in r.json()


@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.analyst])
def test_non_admin_forbidden(db, role):
    c = _client(db, role)
    assert c.get("/api/v1/settings").status_code == 403
    assert c.put("/api/v1/settings", json={}).status_code == 403
