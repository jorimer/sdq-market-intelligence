"""Gobierno de voz de la ruta del Digest (hallazgo D del 2026-07-17).

`build_digest` generaba narrativa reader-facing (vista "Publicaciones") sin NINGÚN
system prompt — sin regla anti-fabricación. Estas regresiones blindan que (a) ahora
se envía un system con esa disciplina y (b) el contrato JSON no se alteró.
"""
import json

import pytest

from shared.publications.digest import _DIGEST_SYSTEM, build_digest


class _FakeResp:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]


def _fake_anthropic(monkeypatch, reply: str):
    """Parchea anthropic.Anthropic para capturar los kwargs de messages.create."""
    import anthropic

    calls = []

    class _FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key
            client = self

            class _Messages:
                @staticmethod
                def create(**kwargs):
                    calls.append(kwargs)
                    return _FakeResp(reply)

            client.messages = _Messages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    return calls


_VALID_JSON = json.dumps({
    "resumen": "La economía creció 5.1% interanual según el informe.",
    "hallazgos": ["El PIB creció 5.1%"],
    "cifras": [{"etiqueta": "PIB", "valor": "5.1% interanual"}],
    "riesgos": ["Presión inflacionaria"],
    "relevancia": {"macro": "Marca el ritmo de la política monetaria"},
})


def test_build_digest_sends_antifabrication_system(monkeypatch):
    # Regresión directa del hallazgo D: antes no se enviaba system ALGUNO.
    calls = _fake_anthropic(monkeypatch, _VALID_JSON)
    build_digest("Texto del informe.", "Informe BCRD", "2026-Q1", api_key="test-key")
    assert len(calls) == 1
    system = calls[0].get("system")
    assert system == _DIGEST_SYSTEM and system  # no vacío
    assert "nunca inventes" in system           # la disciplina anti-fabricación
    assert "JSON" in system                     # sin romper el contrato de salida


def test_build_digest_json_contract_unchanged(monkeypatch):
    # El cambio de system no debe alterar _extract_json/normalize_digest.
    _fake_anthropic(monkeypatch, _VALID_JSON)
    out = build_digest("Texto del informe.", "Informe BCRD", "2026-Q1", api_key="test-key")
    assert out["resumen"].startswith("La economía creció")
    assert out["hallazgos"] == ["El PIB creció 5.1%"]
    assert out["cifras"] == [{"etiqueta": "PIB", "valor": "5.1% interanual"}]
    assert out["riesgos"] == ["Presión inflacionaria"]
    assert out["relevancia"] == {"macro": "Marca el ritmo de la política monetaria"}


def test_build_digest_requires_api_key(monkeypatch):
    from shared.config.settings import settings
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "", raising=False)
    with pytest.raises(ValueError):
        build_digest("Texto.", "Informe", "2026-Q1")
