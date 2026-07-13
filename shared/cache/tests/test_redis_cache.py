"""Tests del cliente Redis de caché: opcionalidad, best-effort y breaker."""
from unittest.mock import MagicMock

import pytest

from shared.cache import redis_cache


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Estado limpio del singleton/breaker en cada test."""
    monkeypatch.setattr(redis_cache, "_client", None)
    monkeypatch.setattr(redis_cache, "_client_failed_at", 0.0)
    yield


def test_sin_redis_url_todo_es_noop(monkeypatch):
    monkeypatch.setattr(redis_cache.settings, "REDIS_URL", "")
    assert redis_cache.cache_get("k") is None
    redis_cache.cache_set("k", "v", 60)  # no lanza
    assert redis_cache.cache_incr_float("k", 1.5, 60) is None


def test_operaciones_con_cliente_mockeado(monkeypatch):
    client = MagicMock()
    client.get.return_value = "hola"
    client.incrbyfloat.return_value = 2.5
    client.ttl.return_value = -1
    monkeypatch.setattr(redis_cache, "_get_client", lambda: client)

    assert redis_cache.cache_get("k") == "hola"
    redis_cache.cache_set("k", "v", 60)
    client.set.assert_called_once_with("k", "v", ex=60)
    assert redis_cache.cache_incr_float("cnt", 2.5, 60) == 2.5
    client.expire.assert_called_once()  # TTL puesto porque ttl() < 0


def test_incr_no_resetea_ttl_existente(monkeypatch):
    client = MagicMock()
    client.incrbyfloat.return_value = 5.0
    client.ttl.return_value = 100  # ya tiene TTL
    monkeypatch.setattr(redis_cache, "_get_client", lambda: client)
    redis_cache.cache_incr_float("cnt", 1.0, 60)
    client.expire.assert_not_called()


def test_error_de_operacion_abre_breaker(monkeypatch):
    monkeypatch.setattr(redis_cache.settings, "REDIS_URL", "redis://x")
    client = MagicMock()
    client.get.side_effect = ConnectionError("down")
    monkeypatch.setattr(redis_cache, "_client", client)

    assert redis_cache.cache_get("k") is None  # no lanza
    # breaker abierto: el cliente se descartó y no se reintenta de inmediato
    assert redis_cache._client is None
    assert redis_cache._client_failed_at > 0
    assert redis_cache._get_client() is None


def test_conexion_fallida_abre_breaker(monkeypatch):
    monkeypatch.setattr(redis_cache.settings, "REDIS_URL", "redis://127.0.0.1:1")

    class _Boom:
        @staticmethod
        def from_url(*a, **k):
            raise ConnectionError("no route")

    import sys
    monkeypatch.setitem(sys.modules, "redis", _Boom)
    assert redis_cache._get_client() is None
    assert redis_cache._client_failed_at > 0
    # segundo intento dentro de la ventana: ni siquiera intenta conectar
    monkeypatch.setitem(sys.modules, "redis", None)
    assert redis_cache._get_client() is None
