"""Tests del orquestador v2: resolución, fusión de dato de motor, gate forward-looking."""
import pytest

import shared.research.decompose as decompose_mod
import shared.research.orchestrator as orch
from shared.registry.signals import GAP, REAL
from shared.research.data_pull import EnginePull
from shared.research.decompose import is_forward_looking
from shared.research.models import Evidence, SubQuestion
from shared.research.resolve import ResolvedEntity, detect_axes


# ─── resolución de eje ─────────────────────────────────────────────────
def test_detect_axes_banking_not_esg():
    # 'riesgo' NO debe activar esg (bug de substring 'esg' en 'riesgo').
    axes = detect_axes("perfil de riesgo de Banco Lafise y su liquidez")
    assert "banking" in axes
    assert "esg" not in axes


def test_is_forward_looking():
    assert is_forward_looking("qué tan expuesto está a un shock en los próximos 12 meses")
    assert is_forward_looking("proyección de la cartera a 2 años")
    assert not is_forward_looking("cuál es el rating actual del banco")


# ─── fusión de evidencia del motor ─────────────────────────────────────
def _pull(label="Banco Lafise", sk="banking"):
    return EnginePull(
        sector_key=sk, entity_label=label, period="2025-12", source="SIB · BCRD",
        payload={"scoring_result": {"overall_score": 78.0, "rating_tier": "A"}},
        evidence=[Evidence(text=f"{label}: rating A, score 78.0/100", source="SIB · BCRD",
                           kind="engine", state=REAL, score=100.0)],
        ok=True)


def test_merge_engine_evidence_makes_subquestion_real():
    sq = SubQuestion(text="perfil de riesgo de Banco Lafise", state=GAP, evidence=[])
    orch._merge_engine_evidence([sq], [_pull()])
    assert sq.state == REAL
    assert "banking" in sq.axes
    assert sq.evidence and sq.evidence[0].source == "SIB · BCRD"


def test_merge_single_subquestion_gets_all_live_pulls():
    # una sola sub-pregunta recibe el motor aunque no matchee por token.
    sq = SubQuestion(text="analiza esto", state=GAP, evidence=[])
    orch._merge_engine_evidence([sq], [_pull()])
    assert sq.state == REAL


def test_forward_gap_declared_when_future_and_engine_present():
    sq = SubQuestion(text="riesgo de Banco Lafise próximos 12 meses", state=REAL,
                     evidence=[_pull().evidence[0]])
    gaps = orch._forward_gaps("riesgo de Banco Lafise en los próximos 12 meses", [sq], [_pull()])
    assert len(gaps) == 1
    assert "prospectiva" in gaps[0].note.lower() or "futuro" in gaps[0].note.lower()


def test_no_forward_gap_when_no_engine_data():
    # sin dato de motor, la brecha la maneja el flujo de retrieval, no _forward_gaps.
    assert orch._forward_gaps("proyección a 12 meses", [], []) == []


# ─── narrativa: degrada a None sin motores ─────────────────────────────
@pytest.mark.asyncio
async def test_narrate_returns_none_without_pulls():
    from shared.research.narrate import narrate_answer
    assert await narrate_answer("una pregunta", []) is None


# ─── end-to-end (sin DB, sin Cerebro): pull inyectado vía monkeypatch ──
@pytest.mark.asyncio
async def test_answer_uses_engine_evidence_and_declares_forward_gap(monkeypatch):
    # Resolver → una entidad bancaria; pull → dato real; retrieval → vacío.
    monkeypatch.setattr(orch, "resolve_targets",
                        lambda q, db: type("T", (), {"entities": [
                            ResolvedEntity("banking", "id1", "Banco Lafise")], "axes": []})())
    monkeypatch.setattr(orch, "pull_entity", lambda db, e: _pull())
    monkeypatch.setattr(decompose_mod, "retrieve",
                        lambda *a, **k: [])  # sin metodología
    ans = await orch.answer_question(
        "¿Cuál es el perfil de riesgo de Banco Lafise y su exposición a un shock de "
        "liquidez en los próximos 12 meses?", db=None, narrate=False)
    # La sub-pregunta se ancló al dato REAL del motor.
    assert any(sq.state == REAL for sq in ans.sub_questions)
    assert ans.coverage_real > 0
    # La parte prospectiva se declaró como brecha, no se rellenó.
    assert any("prospectiva" in g.note.lower() for g in ans.gaps)
    # La fuente del motor aparece.
    assert "SIB · BCRD" in ans.sources
