"""Tests for the BCRD live-API helper (pure-logic paths; network is mocked)."""
import pytest

from shared.data import bcrd_api
from shared.data.bcrd_api import BCRD_VARIABLES, fetch_bcrd_variable


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
    out = fetch_bcrd_variable("secret-token", "inflacion")
    assert captured["json"] == {"token": "secret-token"}
    assert captured["url"].endswith("/api/services/app/MacroVariables/Inflacion")
    assert out["values"][0]["value"] == 4.5
