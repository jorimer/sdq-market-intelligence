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
    DEEP_DIRECTIVE,
    DIRECTION_DISCIPLINE,
    EPISTEMIC_STANDARD,
    NO_META_COMMENTARY,
    REGISTER_NEUTRO,
)
from shared.narrative.numeric_guard import _parse_unsupported

# El system de la ruta legacy: registro de voz + disciplina epistémica + dirección de las
# comparaciones + regla de salida final (anti meta-comentario). Ver claude_engine.generate.
_LEGACY_SYSTEM = (REGISTER_NEUTRO + "\n\n" + EPISTEMIC_STANDARD + "\n\n"
                  + DIRECTION_DISCIPLINE + "\n\n" + NO_META_COMMENTARY)


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
    """Sin axis: un solo mensaje user con el template gordo + directiva lang, y SIN guardrail
    (no hay llamada de juez). El system es registro de voz + disciplina epistémica
    (REGISTER_NEUTRO + EPISTEMIC_STANDARD) — regresión del hallazgo C del 2026-07-17: esta
    ruta corría sin la regla anti-fabricación. Sigue SIN la doctrina/Barra del cerebro."""
    eng, calls = _engine_capturing(monkeypatch)
    ctx = {"score": 77}
    asyncio.run(eng.generate(ctx, template="entity_rating", mode="detailed", lang="es"))

    assert len(calls) == 1 and not _judge_calls(calls)   # legacy no invoca el guardrail
    system = calls[0].get("system") or ""
    assert system == _LEGACY_SYSTEM
    assert REGISTER_NEUTRO in system and EPISTEMIC_STANDARD in system
    assert BARRA_DE_INSIGHT not in system                # no es la ruta cerebro
    assert CEREBRO_IDENTITY not in system
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    expected = _apply_lang(TEMPLATES["entity_rating"].format(context=context_str), "es")
    assert calls[0]["messages"][0]["content"] == expected


def test_axis_with_non_thin_template_stays_legacy(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="executive_summary", axis="banking"))
    # legacy (sin juez): registro de voz + disciplina epistémica, no la Barra del cerebro.
    assert len(calls) == 1
    assert calls[0].get("system") == _LEGACY_SYSTEM
    assert BARRA_DE_INSIGHT not in (calls[0].get("system") or "")


def test_unknown_axis_falls_back_to_legacy_without_keyerror(monkeypatch):
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate({"x": 1}, template="entity_rating", axis="__sin_doctrina__"))
    assert len(calls) == 1
    assert calls[0].get("system") == _LEGACY_SYSTEM
    assert BARRA_DE_INSIGHT not in (calls[0].get("system") or "")


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


def test_insurance_intel_is_wired_to_cerebro(monkeypatch):
    """Regresión (2026-07-27): insurance_intel NO estaba en AXIS_DOCTRINE y sus templates no
    existían en THIN_TEMPLATES → seguros caía a la ruta legacy con el prompt genérico
    executive_summary (sin doctrina de seguros ni Barra de Insight). Este test fija que el eje
    y sus 4 templates estén cableados y que la generación tome la ruta cerebro."""
    from shared.narrative.cerebro import AXIS_DOCTRINE
    assert "insurance_intel" in AXIS_DOCTRINE
    for t in ("insurance_pulse", "insurance_market_context",
              "insurance_peer_positioning", "insurance_entity"):
        assert t in THIN_TEMPLATES, f"falta thin template {t}"
    assert "insurance_intel" in AUDIENCE_FRAMES
    assert "inversionista" in AUDIENCE_FRAMES["insurance_intel"]

    eng, calls = _engine_capturing(monkeypatch)
    ctx = {"entity_name": "Seguros Reservas, S.A.", "isf_score": 66, "banda": "Adecuada"}
    asyncio.run(eng.generate(
        ctx, template="insurance_entity", mode="standard", lang="es",
        axis="insurance_intel", audience="inversionista",
    ))
    gen = _gen_calls(calls)[0]
    # ruta cerebro: system ensamblado (identidad + doctrina de seguros + frame), NO legacy
    assert CEREBRO_IDENTITY in gen["system"]
    assert BARRA_DE_INSIGHT in gen["system"]
    assert AXIS_DOCTRINE["insurance_intel"] in gen["system"]
    assert AUDIENCE_FRAMES["insurance_intel"]["inversionista"] in gen["system"]
    # usa el thin template de seguros, NO el executive_summary genérico de la ruta legacy
    context_str = claude_engine.json.dumps(ctx, indent=2, ensure_ascii=False, default=str)
    assert gen["messages"][0]["content"] == _apply_lang(
        THIN_TEMPLATES["insurance_entity"].format(context=context_str), "es")
    assert "Eres un analista financiero senior" not in gen["messages"][0]["content"]


def test_deep_mode_appends_directive_and_raises_max_tokens(monkeypatch):
    """`mode="deep"`: el override de longitud (DEEP_DIRECTIVE) se anexa al FINAL del
    mensaje de tarea (gana sobre el tope del thin) y max_tokens sube a 4096. En
    `detailed` no aparece y max_tokens=2048."""
    eng, calls = _engine_capturing(monkeypatch)
    asyncio.run(eng.generate(
        {"x": 1}, template="entity_rating", mode="deep",
        axis="banking", audience="comite_credito"))
    gen = _gen_calls(calls)[0]
    user = gen["messages"][0]["content"]
    assert DEEP_DIRECTIVE in user
    assert user.rstrip().endswith(DEEP_DIRECTIVE.rstrip()[-40:])  # va al final
    assert gen["max_tokens"] == 4096

    eng2, calls2 = _engine_capturing(monkeypatch)
    asyncio.run(eng2.generate(
        {"x": 1}, template="entity_rating", mode="detailed",
        axis="banking", audience="comite_credito"))
    gen2 = _gen_calls(calls2)[0]
    assert DEEP_DIRECTIVE not in gen2["messages"][0]["content"]
    assert gen2["max_tokens"] == 2048


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


# ── Semáforo de concurrencia configurable ──────────────────────────────────────
def test_semaphore_reads_setting(monkeypatch):
    """El semáforo global de concurrencia toma su cota de settings.NARRATIVE_MAX_CONCURRENCY
    (techo real de throughput; configurable por env)."""
    monkeypatch.setattr(claude_engine.settings, "NARRATIVE_MAX_CONCURRENCY", 7, raising=False)
    eng = NarrativeEngine()

    async def _cap():
        return eng._get_sem()._value  # valor inicial del semáforo == cota

    assert asyncio.run(_cap()) == 7


def _sem_value(eng):
    async def _cap():
        return eng._get_sem()._value
    return asyncio.run(_cap())


def test_semaphore_invalid_value_falls_back_to_default(monkeypatch):
    # Un valor inválido (0, negativo) NO estrangula: cae al default 10.
    monkeypatch.setattr(claude_engine.settings, "NARRATIVE_MAX_CONCURRENCY", 0, raising=False)
    assert _sem_value(NarrativeEngine()) == 10
    monkeypatch.setattr(claude_engine.settings, "NARRATIVE_MAX_CONCURRENCY", -3, raising=False)
    assert _sem_value(NarrativeEngine()) == 10
