"""Tests de observabilidad: logs JSON, init de Sentry (no-op sin DSN) y health checks."""
import json
import logging

from fastapi.testclient import TestClient

from shared.observability.logging_config import (
    JsonFormatter,
    build_log_config,
    use_json_logs,
)
from shared.observability.sentry import init_sentry
from shared.observability import health as health_mod


# ── JSON logging ─────────────────────────────────────────────────

class TestJsonFormatter:
    def _record(self, **extra):
        rec = logging.makeLogRecord({
            "name": "sdq.test", "levelno": logging.INFO, "levelname": "INFO",
            "msg": "hola %s", "args": ("mundo",),
        })
        for k, v in extra.items():
            setattr(rec, k, v)
        return rec

    def test_emits_valid_json_with_core_fields(self):
        out = JsonFormatter().format(self._record())
        obj = json.loads(out)
        assert obj["level"] == "INFO"
        assert obj["logger"] == "sdq.test"
        assert obj["msg"] == "hola mundo"  # args interpolados
        assert "ts" in obj

    def test_includes_serializable_extras(self):
        out = JsonFormatter().format(self._record(sku="insight:banking", user_id="u1"))
        obj = json.loads(out)
        assert obj["sku"] == "insight:banking"
        assert obj["user_id"] == "u1"

    def test_non_serializable_extra_is_repr(self):
        out = JsonFormatter().format(self._record(obj=object()))
        obj = json.loads(out)  # no explota
        assert "obj" in obj and isinstance(obj["obj"], str)

    def test_exception_is_captured(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = self._record()
            rec.exc_info = sys.exc_info()
            obj = json.loads(JsonFormatter().format(rec))
            assert "ValueError: boom" in obj["exc"]

    def test_use_json_logs_follows_environment(self, monkeypatch):
        from shared.config.settings import settings
        monkeypatch.setattr(settings, "LOG_JSON", False)
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        assert use_json_logs() is False
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        assert use_json_logs() is True

    def test_build_log_config_uses_json_formatter_in_prod(self, monkeypatch):
        from shared.config.settings import settings
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        cfg = build_log_config()
        assert cfg["formatters"]["default"]["()"].endswith("JsonFormatter")


# ── Sentry ───────────────────────────────────────────────────────

class TestSentry:
    def test_no_dsn_is_noop(self, monkeypatch):
        from shared.config.settings import settings
        monkeypatch.setattr(settings, "SENTRY_DSN", "")
        import shared.observability.sentry as s
        monkeypatch.setattr(s, "_initialized", False)
        assert init_sentry() is False


# ── Health checks ────────────────────────────────────────────────

class TestHealth:
    def test_liveness_is_static(self):
        assert health_mod.liveness()["status"] == "ok"

    def test_readiness_ok_when_db_up_redis_unconfigured(self, monkeypatch):
        # DB de test disponible; Redis sin configurar → no bloquea.
        from shared.config.settings import settings
        monkeypatch.setattr(settings, "REDIS_URL", "")
        healthy, payload = health_mod.readiness()
        assert healthy is True
        assert payload["checks"]["database"]["ok"] is True
        assert payload["checks"]["redis"]["configured"] is False

    def test_readiness_503_when_db_down(self, monkeypatch):
        monkeypatch.setattr(health_mod, "_check_db", lambda: (False, {"ok": False, "error": "down"}))
        healthy, payload = health_mod.readiness()
        assert healthy is False
        assert payload["status"] == "degraded"

    def test_readiness_fails_when_configured_redis_down(self, monkeypatch):
        monkeypatch.setattr(health_mod, "_check_redis",
                            lambda: (False, {"ok": False, "configured": True, "error": "x"}))
        healthy, _ = health_mod.readiness()
        assert healthy is False


# ── Endpoint wiring ──────────────────────────────────────────────

class TestHealthEndpoints:
    def _client(self):
        from app.main import app
        return TestClient(app)

    def test_health_live_endpoint(self):
        r = self._client().get("/api/v1/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_endpoint_ok(self, monkeypatch):
        monkeypatch.setattr(health_mod, "_check_db", lambda: (True, {"ok": True}))
        monkeypatch.setattr(health_mod, "_check_redis", lambda: (True, {"ok": True, "configured": False}))
        r = self._client().get("/api/v1/health")
        assert r.status_code == 200

    def test_health_endpoint_503_when_db_down(self, monkeypatch):
        monkeypatch.setattr(health_mod, "_check_db", lambda: (False, {"ok": False, "error": "down"}))
        r = self._client().get("/api/v1/health")
        assert r.status_code == 503
        assert r.json()["status"] == "degraded"
