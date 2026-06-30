"""Tests de la Fase 2 i18n: las narrativas IA salen en el idioma de la request."""
import asyncio

from shared.narrative import claude_engine
from shared.narrative.claude_engine import NarrativeEngine, _apply_lang
from shared.narrative.lang_context import (
    DEFAULT_LANG, get_request_lang, set_request_lang,
)


def test_set_request_lang_validates():
    assert set_request_lang("fr") == "fr"
    assert get_request_lang() == "fr"
    # Inválido / vacío → default es.
    assert set_request_lang("xx") == DEFAULT_LANG
    assert set_request_lang(None) == DEFAULT_LANG
    assert set_request_lang("EN") == "en"  # case-insensitive


def test_apply_lang_appends_directive_only_for_non_default():
    base = "Prompt base en español."
    assert _apply_lang(base, "es") == base  # sin directiva → idéntico
    fr = _apply_lang(base, "fr")
    assert fr.startswith(base) and "français" in fr
    en = _apply_lang(base, "en")
    assert en.startswith(base) and "English" in en


def test_cache_key_differs_by_lang():
    eng = NarrativeEngine()
    ctx = {"a": 1}
    k_es = eng._cache_key(ctx, "executive_summary", "standard", "es")
    k_fr = eng._cache_key(ctx, "executive_summary", "standard", "fr")
    k_en = eng._cache_key(ctx, "executive_summary", "standard", "en")
    assert len({k_es, k_fr, k_en}) == 3  # tres idiomas → tres claves


def test_generate_caches_per_language(monkeypatch):
    """Sin API key cae al fallback, pero la clave de cache namespacea por idioma:
    es y fr generan entradas distintas (no se pisan)."""
    eng = NarrativeEngine()
    monkeypatch.setattr(eng, "_get_client", lambda: None)  # fuerza fallback
    ctx = {"score": 50}
    asyncio.run(eng.generate(ctx, template="executive_summary", lang="es"))
    asyncio.run(eng.generate(ctx, template="executive_summary", lang="fr"))
    assert len(eng._cache) == 2


def test_generate_uses_request_lang_context(monkeypatch):
    """Si no se pasa lang explícito, toma el idioma del contexto de la request."""
    eng = NarrativeEngine()
    captured = {}

    class _FakeMsg:
        def __init__(self, text):
            self.content = [type("C", (), {"text": text})()]
            self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    class _FakeClient:
        class messages:
            @staticmethod
            def create(model, max_tokens, messages, system=None):
                captured["prompt"] = messages[0]["content"]
                return _FakeMsg("ok")

    monkeypatch.setattr(eng, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_MODEL", "test-model", raising=False)

    try:
        set_request_lang("fr")
        asyncio.run(eng.generate({"x": 1}, template="executive_summary"))
        assert "français" in captured["prompt"]  # directiva FR inyectada sin pasar lang
    finally:
        set_request_lang("es")  # restore aunque falle el assert (no filtrar a otros tests)
