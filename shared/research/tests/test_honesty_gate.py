"""Tests del gate de honestidad reforzado — A4.1/A4.2/A4.3 del SPEC_GATE_HONESTIDAD.

Cubre: umbral por-kind propagado por map_subquestion (A4.1/A4.3), la señal question_in_scope
(A4.3) y la verificación de relevancia LLM defensiva (A4.2 — degrada RUBRIC→GAP)."""
import pytest

import shared.research.decompose as decompose_mod
import shared.research.relevance as rel
from shared.research.assemble import assemble_scoping_sections
from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.models import Evidence, SubQuestion
from shared.research.relevance import (
    _extract_bool,
    _needs_check,
    is_method_applicable,
    verify_rubric_relevance,
)


# ─── A4.1/A4.3: map_subquestion propaga el umbral por-kind correcto ─────
def _capture_retrieve(monkeypatch):
    seen = {}

    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True,
                      min_score=0.0, min_score_by_kind=None):
        seen["min_score"] = min_score
        seen["by_kind"] = min_score_by_kind
        return []
    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)
    return seen


def test_in_scope_uses_soft_threshold(monkeypatch):
    seen = _capture_retrieve(monkeypatch)
    decompose_mod.map_subquestion("una sub-pregunta", db=None,
                                  min_anchor_score=7.0, min_anchor_score_soft=10.0,
                                  question_in_scope=True)
    assert seen["min_score"] == 7.0
    assert seen["by_kind"]["doctrine"] == 10.0
    assert seen["by_kind"]["methodology"] == 10.0


def test_offtopic_uses_stricter_threshold(monkeypatch):
    seen = _capture_retrieve(monkeypatch)
    decompose_mod.map_subquestion("una sub-pregunta fuera de alcance", db=None,
                                  min_anchor_score=7.0, min_anchor_score_soft=10.0,
                                  question_in_scope=False)
    assert seen["by_kind"]["doctrine"] == decompose_mod.DEFAULT_MIN_ANCHOR_SCORE_OFFTOPIC
    assert seen["by_kind"]["doctrine"] > 10.0


# ─── A4.2: _needs_check — qué sub-preguntas se re-verifican ─────────────
def _sq(state, kinds):
    ev = [Evidence(text=f"e{k}", source="S", kind=k, state=RUBRIC, score=11.0) for k in kinds]
    return SubQuestion(text="q", evidence=ev, state=state)


def test_needs_check_only_text_only_rubric():
    assert _needs_check(_sq(RUBRIC, ["doctrine"])) is True
    assert _needs_check(_sq(RUBRIC, ["methodology", "bulletin"])) is True
    # un ancla registry (temática por procedencia) exime la verificación
    assert _needs_check(_sq(RUBRIC, ["registry", "doctrine"])) is False
    # REAL/GAP no se verifican
    assert _needs_check(_sq(REAL, ["doctrine"])) is False
    assert _needs_check(SubQuestion(text="q", state=GAP)) is False


# ─── A4.2: _extract_bool ───────────────────────────────────────────────
def test_extract_bool_parses_and_defaults():
    assert _extract_bool('{"aplicable": true}') is True
    assert _extract_bool('{"aplicable": false}') is False
    assert _extract_bool('```json\n{"aplicable": true}\n```') is True
    assert _extract_bool("prosa {\"aplicable\": false} más") is False
    assert _extract_bool("sin json") is None
    assert _extract_bool('{"otra": 1}') is None


# ─── A4.2: is_method_applicable — fail-safe conservador ────────────────
@pytest.mark.asyncio
async def test_is_method_applicable_no_client_is_false(monkeypatch):
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: None)
    # sin Cerebro → NO aplicable (conservador → la sub-pregunta caerá a GAP)
    assert await is_method_applicable("q", ["pasaje"]) is False


@pytest.mark.asyncio
async def test_is_method_applicable_empty_passages_is_false():
    assert await is_method_applicable("q", []) is False


class _Sem:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 2})()


def _mock_cerebro(monkeypatch, response_text):
    import shared.llm.budget as budget
    from shared.narrative.claude_engine import narrative_engine
    client = type("C", (), {"messages": type("M", (), {
        "create": staticmethod(lambda **kw: _Resp(response_text))})()})()
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: client)
    monkeypatch.setattr(narrative_engine, "_get_sem", lambda: _Sem())
    monkeypatch.setattr(budget, "budget_allows", lambda: True)
    monkeypatch.setattr(budget, "record_usage", lambda *a, **k: 0.0)


@pytest.mark.asyncio
async def test_is_method_applicable_true_path(monkeypatch):
    _mock_cerebro(monkeypatch, '{"aplicable": true}')
    assert await is_method_applicable("q", ["un método aplicable"]) is True


@pytest.mark.asyncio
async def test_is_method_applicable_false_path(monkeypatch):
    _mock_cerebro(monkeypatch, '{"aplicable": false}')
    assert await is_method_applicable("q", ["ruido irrelevante"]) is False


@pytest.mark.asyncio
async def test_is_method_applicable_api_error_is_false(monkeypatch):
    import shared.llm.budget as budget
    from shared.narrative.claude_engine import narrative_engine

    def boom(**kw):
        raise RuntimeError("api down")
    client = type("C", (), {"messages": type("M", (), {"create": staticmethod(boom)})()})()
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: client)
    monkeypatch.setattr(narrative_engine, "_get_sem", lambda: _Sem())
    monkeypatch.setattr(budget, "budget_allows", lambda: True)
    assert await is_method_applicable("q", ["x"]) is False


@pytest.mark.asyncio
async def test_is_method_applicable_over_budget_is_false(monkeypatch):
    import shared.llm.budget as budget
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: object())
    monkeypatch.setattr(budget, "budget_allows", lambda: False)
    assert await is_method_applicable("q", ["x"]) is False


# ─── A4.2: verify_rubric_relevance — degrada RUBRIC→GAP ────────────────
@pytest.mark.asyncio
async def test_verify_downgrades_when_not_applicable(monkeypatch):
    async def not_applicable(question, passages, lang="es"):
        return False
    monkeypatch.setattr(rel, "is_method_applicable", not_applicable)

    sq_text = _sq(RUBRIC, ["doctrine"])           # se verifica → degrada
    sq_real = _sq(REAL, ["registry"])             # REAL no se toca
    sq_reg = _sq(RUBRIC, ["registry"])            # rúbrica de registry no se toca
    await verify_rubric_relevance("pregunta", [sq_text, sq_real, sq_reg])
    assert sq_text.state == GAP
    assert sq_text.evidence == []          # #1: evidencia desacreditada descartada
    assert sq_text.related_context == []   # doctrina RUBRIC descartada NO es contexto (no es dato)
    assert "no es método aplicable" in sq_text.note.lower()
    assert sq_real.state == REAL
    assert sq_reg.state == RUBRIC


@pytest.mark.asyncio
async def test_verify_keeps_when_applicable(monkeypatch):
    async def applicable(question, passages, lang="es"):
        return True
    monkeypatch.setattr(rel, "is_method_applicable", applicable)
    sq = _sq(RUBRIC, ["methodology"])
    await verify_rubric_relevance("pregunta", [sq])
    assert sq.state == RUBRIC


@pytest.mark.asyncio
async def test_verify_flag_off_is_noop(monkeypatch):
    from shared.config.settings import settings
    monkeypatch.setattr(settings, "RESEARCH_RELEVANCE_CHECK", False)
    sq = _sq(RUBRIC, ["doctrine"])
    await verify_rubric_relevance("pregunta", [sq])
    assert sq.state == RUBRIC  # deshabilitado → no toca nada


@pytest.mark.asyncio
async def test_verify_check_error_downgrades_conservatively(monkeypatch):
    # #3 (reviewer): una excepción POR-CHECK se aísla (return_exceptions) y se trata como NO
    # aplicable → GAP (el fallback conservador), sin abandonar el lote ni dejar rúbrica.
    async def boom(question, passages, lang="es"):
        raise RuntimeError("api down")
    monkeypatch.setattr(rel, "is_method_applicable", boom)
    sq = _sq(RUBRIC, ["doctrine"])
    await verify_rubric_relevance("pregunta", [sq])   # no lanza
    assert sq.state == GAP


# ─── integración: el orquestador aplica A4.2 end-to-end (Pregunta 3 del piloto) ──
@pytest.mark.asyncio
async def test_orchestrator_downgrades_irrelevant_rubric_to_gap(monkeypatch):
    """Espeja el bug de prod: doctrina irrelevante ancló RUBRIC. Con A4.2 (relevancia=NO),
    la sub-pregunta sale GAP, no un '100% con ancla' falso."""
    import shared.research.orchestrator as orch

    # retrieve devuelve doctrina que cruza el umbral (score alto) pero es irrelevante.
    monkeypatch.setattr(decompose_mod, "retrieve",
                        lambda *a, **k: [{"text": "formatos de salida PDF/Word del reporte",
                                          "source": "Metodología · Estándar de Reporte MIR",
                                          "kind": "methodology", "score": 12.0, "meta": {}}])
    # el verificador de relevancia dice NO aplicable
    async def not_applicable(question, passages, lang="es"):
        return False
    monkeypatch.setattr(rel, "is_method_applicable", not_applicable)

    ans = await orch.answer_question(
        "cuántas cadenas de comida rápida operan y su participación de mercado", db=None)
    # antes: RUBRIC ('100% con ancla'); ahora: GAP declarado.
    assert all(sq.state == GAP for sq in ans.sub_questions)
    assert ans.gate == "scoping"
    assert ans.coverage_real == 0.0
    # #1 (reviewer): la fuente desacreditada NO debe seguir citada en Fuentes.
    assert "Metodología · Estándar de Reporte MIR" not in ans.sources
    assert all(not sq.evidence for sq in ans.sub_questions)


# ─── B (reviewer §Parte B): registry EXTERNO DGII (REAL) también se verifica ─────
def _dgii_ev(state, ref="dgii/contribuyentes/hoteles"):
    return Evidence(text="Contribuyentes activos en la DGII para hoteles: 1.897",
                    source="DGII · Estadísticas de Contribuyentes", kind="registry",
                    state=state, score=8.0, ref=ref)


def test_needs_check_incluye_dgii_real_pero_no_registry_de_eje():
    # DGII (ref dgii/) ancla por solape léxico → se verifica AUNQUE sea REAL
    assert _needs_check(SubQuestion(text="q", evidence=[_dgii_ev(REAL)], state=REAL)) is True
    assert _needs_check(SubQuestion(text="q", evidence=[_dgii_ev(RUBRIC)], state=RUBRIC)) is True
    # registry ATADO a un eje (ref registry/…) sigue exento
    axis = Evidence(text="x", source="Data Registry · Banca", kind="registry", state=REAL,
                    score=9.0, ref="registry/banca/roe")
    assert _needs_check(SubQuestion(text="q", evidence=[axis], state=REAL)) is False


@pytest.mark.asyncio
async def test_verify_degrada_dgii_real_no_pertinente(monkeypatch):
    # "rentabilidad de los hoteles" matchea el CONTEO de contribuyentes por léxico → REAL falso.
    async def not_applicable(question, passages, lang="es"):
        return False
    monkeypatch.setattr(rel, "is_method_applicable", not_applicable)
    sq = SubQuestion(text="rentabilidad de los hoteles", evidence=[_dgii_ev(REAL)], state=REAL)
    await verify_rubric_relevance("rentabilidad de los hoteles", [sq])
    assert sq.state == GAP          # ya no ancla REAL falso
    assert sq.evidence == []
    # el dato REAL descartado se preserva como contexto adyacente (no como ancla)
    assert len(sq.related_context) == 1 and sq.related_context[0].kind == "registry"


@pytest.mark.asyncio
async def test_verify_conserva_dgii_real_pertinente(monkeypatch):
    async def applicable(question, passages, lang="es"):
        return True
    monkeypatch.setattr(rel, "is_method_applicable", applicable)
    sq = SubQuestion(text="cuántos contribuyentes en hoteles", evidence=[_dgii_ev(REAL)], state=REAL)
    await verify_rubric_relevance("cuántos contribuyentes en hoteles", [sq])
    assert sq.state == REAL and sq.evidence   # ancla legítima se conserva


@pytest.mark.asyncio
async def test_verify_dgii_no_pertinente_conserva_ancla_de_eje(monkeypatch):
    # mixta: ancla de eje REAL + DGII no pertinente → cae SOLO la DGII, queda la de eje.
    async def not_applicable(question, passages, lang="es"):
        return False
    monkeypatch.setattr(rel, "is_method_applicable", not_applicable)
    axis = Evidence(text="Variable rentabilidad del eje banca", source="Data Registry · Banca",
                    kind="registry", state=REAL, score=12.0, ref="registry/banca/roe")
    sq = SubQuestion(text="rentabilidad", evidence=[axis, _dgii_ev(REAL)], state=REAL)
    await verify_rubric_relevance("rentabilidad", [sq])
    assert sq.state == REAL
    assert [e.ref for e in sq.evidence] == ["registry/banca/roe"]


@pytest.mark.asyncio
async def test_orchestrator_downgrades_irrelevant_dgii_real_to_gap(monkeypatch):
    """Aceptación del hallazgo del reviewer: un conteo DGII (REAL) que matchea por léxico una
    pregunta de OTRA métrica ya no ancla REAL falso — cae a GAP y no se cita en Fuentes."""
    import shared.research.orchestrator as orch

    monkeypatch.setattr(decompose_mod, "retrieve",
                        lambda *a, **k: [{"text": "Contribuyentes activos en la DGII para hoteles: 1.897",
                                          "source": "DGII · Estadísticas de Contribuyentes",
                                          "kind": "registry", "score": 8.0,
                                          "ref": "dgii/contribuyentes/hoteles",
                                          "meta": {"state": "real"}}])

    async def not_applicable(question, passages, lang="es"):
        return False
    monkeypatch.setattr(rel, "is_method_applicable", not_applicable)

    ans = await orch.answer_question("qué tan rentables son los hoteles en RD", db=None)
    assert all(sq.state == GAP for sq in ans.sub_questions)
    assert not any("DGII" in s for s in ans.sources)   # no ancló → NO en Fuentes
    assert ans.coverage_real == 0.0                     # el contexto NO cuenta para cobertura
    # pero el conteo DGII se surface como "Contexto relacionado" (dato real adyacente)
    assert any(sq.related_context for sq in ans.sub_questions)
    assert "DGII" in ans.sections.get("contexto_relacionado", "")


# ─── render del "Contexto relacionado" (assemble) ──────────────────────
def test_assemble_scoping_incluye_contexto_relacionado():
    ctx = Evidence(text="Contribuyentes activos en la DGII para comida rápida: 1.966 al corte "
                        "29/01/2026. «Cantidad de contribuyentes» no equivale a locales.",
                   source="DGII · Estadísticas de Contribuyentes", kind="registry",
                   state=REAL, score=8.0, ref="dgii/contribuyentes/comida_rapida")
    sq = SubQuestion(text="cuántas cadenas de comida rápida", state=GAP, related_context=[ctx])
    secs = assemble_scoping_sections("q", [sq], sources=[], gaps=[],
                                     coverage_real=0.0, anchored_fraction=0.0)
    assert "contexto_relacionado" in secs
    body = secs["contexto_relacionado"]
    assert "DGII" in body and "1.966" in body
    assert "no responde" in body.lower()          # etiquetado como contexto, no respuesta
    assert "DGII" not in secs["fuentes"]           # NO se cuela en Fuentes


def test_assemble_scoping_sin_contexto_omite_seccion():
    sq = SubQuestion(text="q", state=GAP)
    secs = assemble_scoping_sections("q", [sq], sources=[], gaps=[],
                                     coverage_real=0.0, anchored_fraction=0.0)
    assert "contexto_relacionado" not in secs
