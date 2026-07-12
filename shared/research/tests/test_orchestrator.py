"""Tests del motor de research: descomposición, gate y la regla dura de honestidad (§4).

Núcleo determinista → sin DB ni LLM. Los tests que necesitan controlar la evidencia
parchean ``retrieve`` para inyectar pasajes con procedencia conocida."""
import shared.research.decompose as decompose_mod
from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.decompose import split_question
from shared.research.gate import evaluate_gate
from shared.research.models import (
    GATE_REPORT,
    GATE_SCOPING,
    Evidence,
    SubQuestion,
)
from shared.research.orchestrator import answer_question


# ─── descomposición ────────────────────────────────────────────────────
def test_split_question_on_connectors():
    q = ("¿Qué riesgo regulatorio tiene el sector energía y además cómo está la "
         "resiliencia energética?")
    parts = split_question(q)
    assert len(parts) == 2
    assert "regulatorio" in parts[0].lower()
    assert "resiliencia" in parts[1].lower()


def test_split_question_short_is_single():
    assert split_question("¿riesgo bancario?") == ["¿riesgo bancario?"]


# ─── gate ──────────────────────────────────────────────────────────────
def _sq(state):
    ev = [Evidence(text="x", source="S", kind="registry", state=state, score=1.0)] \
        if state != GAP else []
    return SubQuestion(text="q", evidence=ev, state=state)


def test_gate_report_when_mostly_anchored():
    subs = [_sq(REAL), _sq(REAL), _sq(RUBRIC), _sq(GAP)]  # 25% brecha < 40%
    gate, cov_real, anchored = evaluate_gate(subs)
    assert gate == GATE_REPORT
    assert cov_real == 0.5
    assert anchored == 0.75


def test_gate_scoping_when_too_much_gap():
    subs = [_sq(REAL), _sq(GAP), _sq(GAP)]  # 66% brecha > 40%
    gate, _, anchored = evaluate_gate(subs)
    assert gate == GATE_SCOPING
    assert anchored < 0.4


def test_gate_scoping_when_empty():
    assert evaluate_gate([])[0] == GATE_SCOPING


# ─── round-trip de honestidad (§4): brecha conocida se DECLARA, no se rellena ──
def _patch_retrieve(monkeypatch, mapping):
    """mapping: substring de la sub-pregunta -> lista de pasajes a devolver."""
    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True, min_score=0.0):
        for needle, passages in mapping.items():
            if needle.lower() in query.lower():
                # Respeta el umbral de ancla igual que el retrieval real.
                return [p for p in passages if p.get("score", 0.0) >= min_score]
        return []  # sin match → brecha
    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)


def test_known_gap_is_declared_not_filled(monkeypatch):
    # Pregunta con una parte respondible (energía, dato real) y una brecha deliberada
    # (un tópico ausente del corpus). El reporte DEBE declarar la brecha, no completarla.
    _patch_retrieve(monkeypatch, {
        "energ": [{"text": "IRSE capacidad real", "source": "Data Registry · Energía",
                     "kind": "registry", "score": 9.0, "ref": "registry/energy",
                     "meta": {"sector_key": "energy", "state": "real"}}],
    })
    q = ("Cómo está la resiliencia energética y además cuál es el precio del cacao "
         "en Marte")
    ans = answer_question(q, db=None)

    by_state = {sq.text: sq.state for sq in ans.sub_questions}
    energia = next(sq for sq in ans.sub_questions if "energ" in sq.text.lower())
    marte = next(sq for sq in ans.sub_questions if "marte" in sq.text.lower())

    assert energia.state == REAL                 # anclada a dato real
    assert marte.state == GAP                    # brecha declarada, no rellenada
    assert not marte.evidence                    # sin evidencia adjunta
    assert any(g.sub_question == marte.text for g in ans.gaps)   # declarada en brechas
    # 50% brecha > 40% → gate scoping (no informe con apariencia de completo)
    assert ans.gate == GATE_SCOPING
    assert "marte" in ans.sections["lo_que_no_se_puede"].lower()


def test_fully_anchored_question_yields_report(monkeypatch):
    _patch_retrieve(monkeypatch, {
        "energ": [{"text": "IRSE real", "source": "Data Registry · Energía",
                     "kind": "registry", "score": 9.0,
                     "meta": {"sector_key": "energy", "state": "real"}}],
        "regulatorio": [{"text": "doctrina IRMP", "source": "Doctrina · IRMP",
                         "kind": "doctrine", "score": 8.0, "meta": {}}],
    })
    q = "Cómo está la resiliencia energética y además el riesgo regulatorio"
    ans = answer_question(q, db=None)
    assert ans.gate == GATE_REPORT
    assert ans.anchored_fraction == 1.0
    assert set(ans.sections) >= {"resumen_ejecutivo", "hallazgos", "metodologia",
                                 "fuentes", "limitaciones"}
    # Regla §4: cada hallazgo cita su fuente.
    assert "Data Registry · Energía" in ans.sections["fuentes"]


def test_marginal_match_below_floor_does_not_anchor(monkeypatch):
    # Un roce léxico débil (score bajo el umbral de ancla) NO debe anclar: es el modo
    # de fallo del §6 (colgar una brecha de vocabulario genérico compartido).
    _patch_retrieve(monkeypatch, {
        "cacao": [{"text": "doc que comparte una palabra genérica",
                   "source": "Metodología · X", "kind": "methodology",
                   "score": 4.0, "meta": {}}],  # 4.0 < 7.0 (default) → no ancla
    })
    ans = answer_question("Cuál es el precio del cacao en Marte hoy", db=None)
    sq = ans.sub_questions[0]
    assert sq.state == GAP           # roce marginal filtrado → brecha honesta
    assert not sq.evidence
    # Pero con un umbral laxo (0), ese mismo roce sí anclaría (parámetro tunable).
    ans2 = answer_question("Cuál es el precio del cacao en Marte hoy", db=None,
                           min_anchor_score=0.0)
    assert ans2.sub_questions[0].state == RUBRIC


def test_no_evidence_at_all_is_scoping_with_declared_gaps(monkeypatch):
    _patch_retrieve(monkeypatch, {})  # nada matchea → todo brecha
    ans = answer_question("Pregunta sobre un tema totalmente ausente del corpus", db=None)
    assert ans.gate == GATE_SCOPING
    assert ans.coverage_real == 0.0
    assert ans.gaps                                  # brechas declaradas
    assert "resumen_scoping" in ans.sections
