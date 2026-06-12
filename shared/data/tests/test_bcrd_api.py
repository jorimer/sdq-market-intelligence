"""Tests for the BCRD live-API helper (pure-logic paths; network is mocked)."""
import pytest

from shared.data import bcrd_api
from shared.data.bcrd_api import (
    BCRD_VARIABLES,
    BcrdApiError,
    _unwrap_abp,
    fetch_bcrd_variable,
)


def test_known_variables_have_paths():
    assert "inflacion" in BCRD_VARIABLES
    for path in BCRD_VARIABLES.values():
        assert path.startswith("/api/")


def test_unknown_variable_raises():
    with pytest.raises(ValueError, match="desconocida"):
        fetch_bcrd_variable("tok", "no_existe")


def test_missing_token_raises():
    with pytest.raises(ValueError, match="token"):
        fetch_bcrd_variable("", "inflacion")


def test_posts_token_in_body(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "Inflación", "values": [{"period": "2025-01", "value": 4.5}]}

    def _fake_post(url, json, timeout, headers):  # noqa: A002 — mirror httpx kwarg
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(bcrd_api.httpx, "post", _fake_post)
    out = fetch_bcrd_variable("  secret-token\n", "inflacion")
    assert captured["json"] == {"token": "secret-token"}  # trimmed
    assert captured["url"].endswith("/api/services/app/MacroVariables/Inflacion")
    assert out["values"][0]["value"] == 4.5


# ── ABP envelope handling ─────────────────────────────────────────
def test_unwrap_abp_rejected_token_raises_auth_error():
    payload = {
        "result": None, "success": False,
        "error": {"message": "Credenciales de acceso inválidas"},
    }
    with pytest.raises(BcrdApiError) as ei:
        _unwrap_abp(payload)
    assert ei.value.is_auth is True
    assert "Credenciales" in ei.value.message


def test_unwrap_abp_unwraps_success_envelope():
    payload = {"result": {"name": "Inflación", "values": [1, 2]}, "success": True}
    out = _unwrap_abp(payload)
    assert out == {"name": "Inflación", "values": [1, 2]}


def test_unwrap_abp_passes_through_bare_payload():
    payload = {"name": "x", "values": []}
    assert _unwrap_abp(payload) is payload


def test_fetch_raises_bcrd_error_on_rejected_token(monkeypatch):
    class _Resp:
        def json(self):
            return {"success": False, "error": {"message": "Token inválido"}}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(bcrd_api.httpx, "post", lambda *a, **k: _Resp())
    with pytest.raises(BcrdApiError) as ei:
        fetch_bcrd_variable("bad", "inflacion")
    assert ei.value.is_auth is True
