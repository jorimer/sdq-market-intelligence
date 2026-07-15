"""SPEC-4 — eje base de sector desde bcrd_sectors: ningún sector con dato del BCRD cae a cobertura 0.

Usa el fixture ``bcrd_sectors.json`` (las 17 hojas, offline) — no toca red.
"""
from __future__ import annotations

import pytest

from shared.research.data_pull import pull_axis, pull_sector_base
from shared.research.resolve import detect_axes
from shared.research.sector_base import BASE_SECTORS, is_base_sector


@pytest.mark.parametrize("q,slug", [
    ("¿Qué situación tiene el sector minero en República Dominicana?", "mineria"),
    ("¿Cómo está el sector salud en RD?", "salud"),
    ("desempeño del transporte y almacenamiento", "transporte"),
    ("¿cómo va el sector financiero dominicano?", "financiero"),
    ("situación de la enseñanza en el país", "ensenanza"),
])
def test_base_sector_questions_route(q, slug):
    """Una pregunta de sector base resuelve su slug (antes: ningún eje → scoping)."""
    assert slug in detect_axes(q), f"{slug} no ruteó: {q!r}"


def test_pull_sector_base_yields_real_evidence():
    """El pull base trae aporte al VAB + crecimiento reales del fixture, con fuente BCRD."""
    pull = pull_sector_base("mineria")
    assert pull is not None and pull.ok
    assert pull.evidence, "sin evidencia"
    assert "Valor Agregado" in pull.evidence[0].text
    assert "BCRD" in pull.source
    assert pull.payload.get("base_sector") is True


def test_financiero_bridges_to_banking():
    """SPEC-2: el sector financiero (VAB) tiende un puente al eje de banca."""
    pull = pull_sector_base("financiero")
    assert pull is not None and pull.ok
    assert any("banca" in e.text.lower() for e in pull.evidence), "falta el puente a banca"


def test_pull_axis_no_scoping_for_base_sectors():
    """`pull_axis` (sin db) devuelve un pull vivo para toda hoja base — no vacío."""
    for slug in BASE_SECTORS:
        pull = pull_axis(None, slug)
        assert pull.ok, f"{slug} no rindió pull base (caería a scoping)"
        assert pull.evidence


def test_non_base_slug_returns_none():
    """Un slug que no es hoja base no fabrica pull base."""
    assert pull_sector_base("banking") is None
    assert not is_base_sector("tourism")


@pytest.mark.asyncio
async def test_base_sector_answers_with_coverage_e2e(monkeypatch):
    """E2E (resolve + pull reales; narración/deep mockeados): una pregunta de sector base
    ya NO cae a scoping — acredita cobertura con la ficha del BCRD. Prueba la ruta de prod
    (narrate=True, db truthy), no el atajo db=None que se salta la cosecha de ejes."""
    import shared.research.decompose as decompose_mod
    import shared.research.orchestrator as orch

    monkeypatch.setattr(decompose_mod, "retrieve", lambda *a, **k: [])

    async def no_deep(question, db, targets, forward, pulls=None):
        return None
    monkeypatch.setattr(orch, "build_synthesis_report", no_deep)

    async def no_narr(*a, **k):
        return None
    monkeypatch.setattr(orch, "narrate_answer", no_narr)

    ans = await orch.answer_question(
        "¿Qué situación tiene el sector minero en República Dominicana?",
        db=object(), narrate=True)
    d = ans.to_dict()
    assert d["gate"] != "scoping", f"debería reportar, no scoping: {d['gate']}"
    assert d["coverage_real"] > 0, "la ficha base del BCRD debe acreditar el ledger"
    assert any("origen" in s.lower() or "valor agregado" in s.lower()
               for s in d.get("sources", [])), f"sin fuente BCRD: {d.get('sources')}"
