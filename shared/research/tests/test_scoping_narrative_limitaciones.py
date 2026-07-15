"""Regresión Hallazgos 8, 9 y 10 (familia "contenido perdido / mal formado en Scoping Report").

H8: la narrativa del Cerebro (narrate_answer, template research_answer) se calculaba y se
    DESCARTABA en el scoping — assemble_scoping_sections no tenía parámetro `narrative`.
H9: el Scoping Report no traía sección "Limitaciones" pese a tener todos los insumos
    (cobertura, brechas, sub-preguntas) que el informe completo ya usa.
H10: una pregunta pegada con saltos de línea de wrapping se fragmentaba en sub-preguntas sin
    sentido (`_CONNECTORS` parte en `\n`) — se normaliza el whitespace antes de decompose.
"""
import pytest

import shared.research.decompose as decompose_mod
import shared.research.orchestrator as orch
from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.assemble import (
    _limitaciones_lines,
    assemble_report_sections,
    assemble_scoping_sections,
)
from shared.research.data_pull import EnginePull
from shared.research.models import DeclaredGap, Evidence, SubQuestion


def _anchored_sq(text="papel del turismo en el crecimiento"):
    ev = [Evidence(text="ITT 93.0/100 (banda Fuerte)", source="BCRD turismo · MITUR",
                   kind="engine", state=REAL, score=95.0)]
    return SubQuestion(text=text, evidence=ev, axes=["tourism"], state=REAL)


def _gap_sq(text="cómo se compara con Centroamérica y el Caribe"):
    return SubQuestion(text=text, state=GAP,
                       note="Sin evidencia con procedencia en el corpus ni el Data Registry.")


# ─── H8: narrativa como antesala de "lo que se puede contestar hoy" ────
def test_scoping_narrative_antesala_before_bullets():
    narr = ("El turismo sostiene el crecimiento con ITT fuerte, pero la comparación regional "
            "queda fuera de alcance por falta de panel Centroamérica/Caribe.")
    secs = assemble_scoping_sections("q", [_anchored_sq(), _gap_sq()], sources=["BCRD"],
                                     gaps=[DeclaredGap("cómo se compara", "sin panel regional")],
                                     coverage_real=0.5, anchored_fraction=0.5, narrative=narr)
    los = secs["lo_que_si_se_puede"]
    assert narr in los                                  # la síntesis aparece
    assert los.index("fuera de alcance") < los.index("Evidencia:")   # ANTES de los bullets


def test_scoping_without_narrative_degrades_gracefully():
    # sin Cerebro (narrate_answer→None) el scoping se arma igual, solo sin antesala.
    secs = assemble_scoping_sections("q", [_anchored_sq(), _gap_sq()], sources=["BCRD"],
                                     gaps=[], coverage_real=0.5, anchored_fraction=0.5,
                                     narrative=None)
    los = secs["lo_que_si_se_puede"]
    assert los.startswith("###")                        # arranca directo en el primer hallazgo
    assert "limitaciones" in secs                       # H9 sigue presente sin narrativa


# ─── H9: el scoping declara sus Limitaciones ──────────────────────────
def test_scoping_has_limitaciones_with_gap_and_coverage():
    gaps = [DeclaredGap("cómo se compara ese desempeño con Centroamérica",
                        "sin panel regional", candidate_source="BCRD · pib_gasto_retro.xlsx")]
    secs = assemble_scoping_sections("q", [_anchored_sq(), _gap_sq()], sources=["BCRD"],
                                     gaps=gaps, coverage_real=0.5, anchored_fraction=0.5)
    assert "limitaciones" in secs
    lim = secs["limitaciones"]
    assert "Cobertura de la respuesta" in lim
    assert "Brechas declaradas" in lim
    assert "cómo se compara ese desempeño con Centroamérica" in lim
    assert "BCRD · pib_gasto_retro.xlsx" in lim         # fuente candidata citada


def test_scoping_rubric_notice_in_limitaciones():
    sq_rub = SubQuestion(text="q", state=RUBRIC,
                         evidence=[Evidence(text="x", source="Doctrina", kind="doctrine",
                                            state=RUBRIC, score=11.0)])
    secs = assemble_scoping_sections("q", [sq_rub, _gap_sq()], sources=[], gaps=[],
                                     coverage_real=0.0, anchored_fraction=0.5)
    assert "rúbrica declarada" in secs["limitaciones"].lower()


# ─── el helper compartido produce lo MISMO en informe y scoping (no drift) ──
def test_limitaciones_shared_between_report_and_scoping():
    sqs = [_anchored_sq(), _gap_sq()]
    gaps = [DeclaredGap("cómo se compara", "sin panel")]
    rep = assemble_report_sections("q", sqs, ["BCRD"], gaps, 0.5, 0.5)
    sco = assemble_scoping_sections("q", sqs, ["BCRD"], gaps, 0.5, 0.5)
    expected = _limitaciones_lines(gaps, 0.5, 0.5, sqs)
    assert rep["limitaciones"] == expected == sco["limitaciones"]


# ─── integración: el orquestador CABLEA la narrativa y las limitaciones al scoping ──
def _tourism_pull():
    return EnginePull(
        sector_key="tourism", entity_label="SDQ Tourism Intelligence", period="2025",
        source="BCRD turismo · MITUR",
        payload={"index": {"score": 93.0}},
        evidence=[Evidence(text="ITT 93.0/100 (banda Fuerte) · período 2025",
                           source="BCRD turismo · MITUR", kind="engine", state=REAL, score=95.0)],
        ok=True)


@pytest.mark.asyncio
async def test_orchestrator_wires_narrative_and_limitaciones_into_scoping(monkeypatch):
    """La corrida real (narrate=True, gate=scoping, live_pulls presente): la narrativa del
    Cerebro y la sección Limitaciones llegan a la ResearchAnswer del scoping."""
    class T:
        entities: list = []
        axes = ["tourism"]
        context: list = []
        reasons: dict = {}
    monkeypatch.setattr(orch, "resolve_targets", lambda q, db: T())

    async def no_route(question, db):
        return []
    monkeypatch.setattr(orch, "route_domains", no_route)
    monkeypatch.setattr(orch, "pull_axis", lambda db, ax: _tourism_pull())
    monkeypatch.setattr(decompose_mod, "retrieve", lambda *a, **k: [])   # 2ª cláusula → GAP

    async def no_deep(question, db, targets, forward, pulls=None):
        return None
    monkeypatch.setattr(orch, "build_synthesis_report", no_deep)

    async def fake_narr(question, pulls, **k):
        return ("El turismo sostiene el crecimiento (ITT fuerte); la comparación regional "
                "queda declarada fuera de alcance por falta de panel.")
    monkeypatch.setattr(orch, "narrate_answer", fake_narr)

    # 2 cláusulas por el separador duro '?': la 1ª ancla (tourism), la 2ª queda GAP → scoping.
    q = ("¿Qué papel juega el turismo en el crecimiento dominicano? "
         "¿Cómo se compara con el promedio de Centroamérica y el Caribe?")
    ans = await orch.answer_question(q, db=object(), narrate=True)

    assert ans.gate == "scoping"
    # H8: la narrativa del Cerebro aparece como antesala, antes de los bullets de evidencia
    los = ans.sections["lo_que_si_se_puede"]
    assert "fuera de alcance por falta de panel" in los
    assert los.index("sostiene el crecimiento") < los.index("Evidencia:")
    # H9: la sección Limitaciones existe, en las secciones y en el orden de render
    assert "limitaciones" in ans.sections
    assert "limitaciones" in ans.section_order
    assert "Cobertura de la respuesta" in ans.sections["limitaciones"]


# ─── H10: la pregunta con saltos de línea de wrapping NO se fragmenta ──
@pytest.mark.asyncio
async def test_question_with_embedded_newlines_is_not_fragmented(monkeypatch):
    """Reproducción del PDF prod de turismo: la pregunta se pegó con `\n` de wrapping y salió
    fragmentada en 4 sub-preguntas sin sentido ('el crecimiento dominicano', 'cómo se compara
    ese'). Con la normalización previa a decompose, se parte en 2 cláusulas coherentes."""
    monkeypatch.setattr(decompose_mod, "retrieve", lambda *a, **k: [])   # todo GAP, determinista
    q_multilinea = ("¿Qué papel juegan el turismo, la minería y la construcción en\n"
                    "el crecimiento dominicano, y cómo se compara ese\n"
                    "desempeño con el promedio de Centroamérica y el Caribe?")
    ans = await orch.answer_question(q_multilinea, db=None, narrate=False)

    # la pregunta guardada queda en una sola línea (portada y cuerpo salen limpios)
    assert "\n" not in ans.question
    textos = [sq.text for sq in ans.sub_questions]
    # se parte en 2 cláusulas coherentes (por ', y cómo'), no en 4 fragmentos
    assert len(textos) == 2
    assert any("turismo" in t and "construcción" in t and "crecimiento dominicano" in t
               for t in textos)
    assert any("compara" in t and "Centroamérica" in t and "Caribe" in t for t in textos)
    # ninguno de los fragmentos rotos de antes aparece como sub-pregunta entera
    assert "el crecimiento dominicano" not in textos
    assert "cómo se compara ese" not in textos
