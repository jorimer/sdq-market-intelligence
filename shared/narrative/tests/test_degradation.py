"""Detección de narrativa degradada a fallback estático (guard anti-PDF-hueco).

Cuando el motor IA no puede generar (sin API key, outage/429 sostenido o corte de
presupuesto) devuelve un ``NarrativeResult`` con ``model_used='static_fallback'`` y un texto
de relleno. Los productos descartan ``model_used`` (devuelven ``{sección: texto}``), así que
el ensamblado detecta la degradación sobre el TEXTO. Estos tests fijan el contrato del
detector: caza todos los fallbacks del motor y NADA legítimo.
"""
import asyncio

import shared.narrative.claude_engine as ce
from shared.narrative.claude_engine import (
    STATIC_FALLBACK_GENERIC,
    STATIC_FALLBACK_MODEL,
    STATIC_FALLBACKS,
    NarrativeDegradedError,
    degraded_sections,
    is_static_fallback_text,
    narrative_engine,
)

# Templates reales que usan los Deep Dives premium de seguros/pensiones/banca.
_DEEP_DIVE_TEMPLATES = [
    "insurance_entity", "insurance_peer_positioning", "insurance_market_context",
    "pension_entity", "pension_peer_positioning", "pension_portfolio_context",
    "sector_decision", "banking_summary", "banking_risk",
]


def test_generic_and_per_template_fallbacks_are_detected():
    assert is_static_fallback_text(STATIC_FALLBACK_GENERIC)
    for text in STATIC_FALLBACKS.values():
        assert is_static_fallback_text(text), text[:40]


def test_engine_fallback_output_is_detected_for_every_deep_dive_template():
    """El motor SIN key degrada: cada template de Deep Dive → static_fallback + detectado.
    (El conftest raíz neutraliza ANTHROPIC_API_KEY, así que la ruta de fallback es la viva
    aunque el .env local tenga una key real.)"""
    for tmpl in _DEEP_DIVE_TEMPLATES:
        res = asyncio.run(narrative_engine.generate(
            context={"x": 1}, template=tmpl, axis="pension_intel"))
        assert res.model_used == STATIC_FALLBACK_MODEL, tmpl
        assert is_static_fallback_text(res.text), tmpl


def test_real_prose_and_legitimate_static_sections_are_not_flagged():
    """Cero falsos positivos: prosa real, limitaciones, muestras curadas y textos vacíos."""
    from modules.insurance_intel import products as ins
    from modules.pension_intel import products as pen
    legit = [
        "La aseguradora lidera en solvencia con un margen de 2.3 puntos frente al promedio.",
        ins._LIMITATIONS,
        ins._NO_DATA,
        ins._SAMPLE_ASSESSMENT,
        pen._LIMITATIONS_ABSOLUTE,
        pen._SAMPLE_NARRATIVES["pension_assessment"],
        pen._SAMPLE_NARRATIVES["early_warning"],
        "", "   ", None, 123,
    ]
    for txt in legit:
        assert not is_static_fallback_text(txt), repr(txt)[:60]


def test_degraded_sections_lists_only_degraded_analysis_sections():
    narratives = {
        "assessment": STATIC_FALLBACK_GENERIC,          # degradada
        "peer": "Prosa real de análisis competitivo.",   # sana
        "reco": STATIC_FALLBACKS["banking_risk"],         # degradada (por-template)
        "limitations": "Texto legítimo de limitaciones metodológicas.",  # sana
    }
    got = degraded_sections(narratives, ["assessment", "peer", "reco", "limitations"])
    assert got == ["assessment", "reco"]


def test_degraded_sections_tolerates_missing_keys_and_none():
    assert degraded_sections({}, ["a", "b"]) == []
    assert degraded_sections(None, ["a"]) == []


def test_narrative_degraded_error_carries_sections():
    err = NarrativeDegradedError(["a", "b"])
    assert err.sections == ["a", "b"]
    assert "2 sección" in str(err) and "a, b" in str(err)


def test_guard_is_cause_agnostic_api_error_matches_budget_cutoff(monkeypatch):
    """Lo de un outage real: hay key, pero el API revienta. Debe degradar con el MISMO
    marcador que el corte de presupuesto — así el guard cubre AMBAS causas por igual."""
    class _Boom:
        class messages:
            @staticmethod
            def create(*a, **k):
                raise RuntimeError("overloaded_error: 529 (simulado)")

    eng = ce.NarrativeEngine()
    monkeypatch.setattr(eng, "_get_client", lambda: _Boom())
    monkeypatch.setattr(ce, "budget_allows", lambda: True)  # aísla la causa "error de API"
    for kwargs in ({"axis": "pension_intel", "template": "pension_entity"},  # ruta cerebro
                   {"template": "market_brief"}):                            # ruta legacy
        res = asyncio.run(eng.generate(context={"x": 1}, **kwargs))
        assert res.model_used == STATIC_FALLBACK_MODEL, kwargs
        assert is_static_fallback_text(res.text), kwargs
