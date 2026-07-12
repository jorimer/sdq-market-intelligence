"""Tests del instrumento de piloto (Fase 2) y la exportación a documento (Fase 5)."""
import shared.research.decompose as decompose_mod
from shared.research.export import ordered_sections, to_markdown
from shared.research.models import GATE_SCOPING
from shared.research.orchestrator import answer_question
from shared.research.pilot import run_pilot


def _patch(monkeypatch, mapping):
    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True, min_score=0.0):
        for needle, passages in mapping.items():
            if needle.lower() in query.lower():
                return [p for p in passages if p.get("score", 0.0) >= min_score]
        return []
    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)


def test_run_pilot_captures_coverage(monkeypatch):
    _patch(monkeypatch, {
        "energ": [{"text": "IRSE real", "source": "Data Registry · Energía",
                   "kind": "registry", "score": 9.0,
                   "meta": {"sector_key": "energy", "state": "real"}}],
    })
    report = run_pilot(["Cómo está la resiliencia energética",
                        "Precio del cacao en Marte hoy mismo"], db=None)
    assert report.summary["n"] == 2
    assert report.rows[0].gate == "report"          # anclado a dato real
    assert report.rows[0].coverage_real == 1.0
    assert report.rows[1].gate == GATE_SCOPING       # sin evidencia → scoping
    # markdown de piloto lista ambas y deja las horas como campo a completar.
    md = report.to_markdown()
    assert "Piloto manual" in md and "h DD actual" in md
    assert report.rows[0].hours_manual_dd is None    # no se fabrica


def test_export_ordered_sections_report(monkeypatch):
    _patch(monkeypatch, {
        "energ": [{"text": "IRSE real", "source": "Data Registry · Energía",
                   "kind": "registry", "score": 9.0,
                   "meta": {"sector_key": "energy", "state": "real"}}],
    })
    ans = answer_question("Cómo está la resiliencia energética del sistema", db=None)
    titles = [t for t, _ in ordered_sections(ans)]
    assert titles[0] == "Resumen ejecutivo"
    assert "Limitaciones" in titles
    md = to_markdown(ans)
    assert "SDQ · Market Intelligence" in md
    assert "Metodología" in md


def test_export_scoping_order(monkeypatch):
    _patch(monkeypatch, {})  # todo brecha → scoping
    ans = answer_question("Tema completamente ausente del corpus propio", db=None)
    titles = [t for t, _ in ordered_sections(ans)]
    assert titles[0] == "Alcance"
    assert "Lo que no se puede contestar hoy" in titles
