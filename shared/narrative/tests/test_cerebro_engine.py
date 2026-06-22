"""Motor — la ruta cerebro (axis=) ensambla system+thin y aplica el guardrail numérico
(juez Haiku + regenerar-una-vez); la ruta legacy (sin axis) queda byte-idéntica y SIN
guardrail."""
import asyncio

from shared.narrative import claude_engine
from shared.narrative.claude_engine import TEMPLATES, THIN_TEMPLATES, NarrativeEngine, _apply_lang
from shared.narrative.cerebro import (
    AUDIENCE_FRAMES,
    BARRA_DE_INSIGHT,
    CEREBRO_IDENTITY,
)
from shared.narrative.numeric_guard import _parse_unsupported


class _FakeMsg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _is_judge(kwargs) -> bool:
    return "verificador" in (kwargs.get("system") or "")


def _engine_capturing(monkeypatch, judge_replies=None):
    """Engine whose client records EVERY create call. Judge calls (system del verificador)
    devuelven sucesivamente *judge_replies* (default '{"unsupported": []}' = limpio);
    las de generación devuelven un insight fijo."""
    eng = NarrativeEngine()
    calls = []
    queue = list(judge_replies or [])

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                calls.append(kwargs)
                if _is_judge(kwargs):
                    return _FakeMsg(queue.pop(0) if queue else '{"unsupported": []}')
                return _FakeMsg("INSIGHT")

    monkeypatch.setattr(eng, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_GUARD_MODEL", "test-judge", raising=False)
    return eng, calls


def _gen_calls(calls):
    return [c for c in calls if not _is_judge(c)]


def _judge_calls(calls):
    return [c for c in calls if _is_judge(c)]


# ── Ruta legacy ───────────────────────────────────────────────────────────────
def test_legacy_route_is_byte_identical(monkeypatch):
    """Sin axis: un solo mensaje user, SIN system, con el template gordo + directiva lang,
    y SIN guardrail (no hay llamada de juez)."""
    eng, calls = _engine_capturing(monkeypatch)
    ctx = {"score": 77}
    asyncio.run(eng.generate(ctx, template="entity_rating", mode="detailed", lang="es"))

    assert len(calls) == 1 and not _judge_calls(calls)   # legacy no invoca el guardrail
    assert "system" not in calls[0]
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    expected = _apply_lang(TEMPLATES["entity_rating"].format(context=context_str), "es")
    assert calls[0]["messages"][0]["content"] == expected


def test_axis_with_non_thin_template_stays_legacy(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="executive_summary", axis="banking"))
    assert len(calls) == 1 and "system" not in calls[0]   # legacy, sin juez


def test_unknown_axis_falls_back_to_legacy_without_keyerror(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="entity_rating", axis="__sin_doctrina__"))
    assert len(calls) == 1 and "system" not in calls[0]


# ── Ruta cerebro ────────────────────────────────────────────────────────────────
def test_cerebro_route_uses_system_and_thin(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    ctx = {"score": 77}
    res = asyncio.run(eng.generate(
        ctx, template="entity_rating", mode="detailed", lang="es",
        axis="banking", audience="supervisor",
    ))
    gen = _gen_calls(calls)[0]
    assert CEREBRO_IDENTITY in gen["system"]
    assert BARRA_DE_INSIGHT in gen["system"]
    assert AUDIENCE_FRAMES["banking"]["supervisor"] in gen["system"]
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    assert gen["messages"][0]["content"] == _apply_lang(
        THIN_TEMPLATES["entity_rating"].format(context=context_str), "es")
    assert "Eres un analista" not in gen["messages"][0]["content"]
    # guardrail corrió (1 juez) y quedó limpio
    assert len(_judge_calls(calls)) == 1
    assert res.guard_unsupported == []


def test_cerebro_unknown_audience_falls_back_to_default(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="indicator_insight", axis="banking", audience="zzz"))
    assert AUDIENCE_FRAMES["banking"]["comite_credito"] in _gen_calls(calls)[0]["system"]


def test_cache_key_differs_by_axis_and_audience():
    eng = NarrativeEngine()
    ctx = {"a": 1}
    base = eng._cache_key(ctx, "entity_rating", "detailed", "es")
    with_axis = eng._cache_key(ctx, "entity_rating", "detailed", "es", "banking", "comite_credito")
    other_aud = eng._cache_key(ctx, "entity_rating", "detailed", "es", "banking", "supervisor")
    assert len({base, with_axis, other_aud}) == 3


# ── Guardrail numérico ──────────────────────────────────────────────────────────
def test_guardrail_regenerates_once_when_flagged(monkeypatch):
    """El juez marca una cifra en la 1ª; la regeneración (con CORRECCIÓN) queda limpia."""
    eng, calls = _engine_capturing(
        monkeypatch, judge_replies=['{"unsupported": ["83.42 — no está en la serie"]}',
                                    '{"unsupported": []}'])
    res = asyncio.run(eng.generate(
        {"x": 1}, template="entity_rating", axis="banking", audience="comite_credito"))
    assert len(_gen_calls(calls)) == 2          # generó dos veces (regen-una-vez)
    assert len(_judge_calls(calls)) == 2        # verificó ambas
    # la 2ª generación lleva la corrección con la cifra marcada
    assert "CORRECCIÓN OBLIGATORIA" in _gen_calls(calls)[1]["messages"][0]["content"]
    assert "83.42" in _gen_calls(calls)[1]["messages"][0]["content"]
    assert res.guard_unsupported == []          # quedó limpio tras regenerar
    # tokens acumulan ambas llamadas de generación
    assert res.tokens_used == 60


def test_guardrail_serves_flagged_when_persists(monkeypatch):
    """Si tras regenerar el juez sigue marcando, se sirve igual (best-effort) con el flag."""
    eng, calls = _engine_capturing(
        monkeypatch, judge_replies=['{"unsupported": ["X"]}', '{"unsupported": ["X"]}'])
    res = asyncio.run(eng.generate(
        {"x": 1}, template="entity_rating", axis="banking", audience="comite_credito"))
    assert len(_gen_calls(calls)) == 2
    assert res.text == "INSIGHT"                # nunca se vacía el insight
    assert res.guard_unsupported == ["X"]       # marcado para monitoreo


def test_parse_unsupported_tolerant():
    assert _parse_unsupported('{"unsupported": []}') == []
    assert _parse_unsupported('texto ```{"unsupported": ["12.3 — x"]}``` fin') == ["12.3 — x"]
    assert _parse_unsupported("no json") == []
    assert _parse_unsupported('{"otra": 1}') == []
