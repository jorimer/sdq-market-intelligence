"""Motor — la ruta cerebro (axis=) ensambla system+thin; la ruta legacy (sin axis)
queda byte-idéntica al comportamiento actual."""
import asyncio

from shared.narrative import claude_engine
from shared.narrative.claude_engine import TEMPLATES, THIN_TEMPLATES, NarrativeEngine, _apply_lang
from shared.narrative.cerebro import (
    AUDIENCE_FRAMES,
    BARRA_DE_INSIGHT,
    CEREBRO_IDENTITY,
)


class _FakeMsg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _engine_capturing(monkeypatch):
    """Engine whose client records every messages.create kwarg set."""
    eng = NarrativeEngine()
    captured = {}

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured.clear()
                captured.update(kwargs)
                return _FakeMsg("ok")

    monkeypatch.setattr(eng, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    return eng, captured


def test_legacy_route_is_byte_identical(monkeypatch):
    """Sin axis: un solo mensaje user, SIN system, con el template gordo + directiva lang."""
    eng, captured = _engine_capturing(monkeypatch)
    ctx = {"score": 77}
    asyncio.run(eng.generate(ctx, template="entity_rating", mode="detailed", lang="es"))

    assert "system" not in captured  # legacy NO usa system
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    expected = _apply_lang(TEMPLATES["entity_rating"].format(context=context_str), "es")
    assert captured["messages"][0]["content"] == expected


def test_cerebro_route_uses_system_and_thin(monkeypatch):
    eng, captured = _engine_capturing(monkeypatch)
    ctx = {"score": 77}
    asyncio.run(eng.generate(
        ctx, template="entity_rating", mode="detailed", lang="es",
        axis="banking", audience="supervisor",
    ))
    # system ensamblado con núcleo + frame de la audiencia pedida
    assert "system" in captured
    assert CEREBRO_IDENTITY in captured["system"]
    assert BARRA_DE_INSIGHT in captured["system"]
    assert AUDIENCE_FRAMES["banking"]["supervisor"] in captured["system"]
    # user = template THIN (no el gordo: el thin no dice "Eres un analista…")
    user = captured["messages"][0]["content"]
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    assert user == _apply_lang(THIN_TEMPLATES["entity_rating"].format(context=context_str), "es")
    assert "Eres un analista" not in user


def test_cerebro_unknown_audience_falls_back_to_default(monkeypatch):
    eng, captured = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate(
        {"x": 1}, template="indicator_insight", axis="banking", audience="zzz",
    ))
    assert AUDIENCE_FRAMES["banking"]["comite_credito"] in captured["system"]


def test_axis_with_non_thin_template_stays_legacy(monkeypatch):
    """axis presente pero template sin versión thin → ruta legacy (sin system)."""
    eng, captured = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="executive_summary", axis="banking"))
    assert "system" not in captured


def test_cache_key_differs_by_axis_and_audience():
    eng = NarrativeEngine()
    ctx = {"a": 1}
    base = eng._cache_key(ctx, "entity_rating", "detailed", "es")
    with_axis = eng._cache_key(ctx, "entity_rating", "detailed", "es", "banking", "comite_credito")
    other_aud = eng._cache_key(ctx, "entity_rating", "detailed", "es", "banking", "supervisor")
    assert len({base, with_axis, other_aud}) == 3
