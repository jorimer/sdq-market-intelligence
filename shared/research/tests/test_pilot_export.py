"""Tests del instrumento de piloto (Fase 2) y la exportación a documento (Fase 5)."""
import pytest
import shared.research.decompose as decompose_mod
from shared.research.export import ordered_sections, to_markdown
from shared.research.models import GATE_SCOPING
from shared.research.orchestrator import answer_question
from shared.research.pilot import run_pilot


def _patch(monkeypatch, mapping):
    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True, min_score=0.0, min_score_by_kind=None):
        for needle, passages in mapping.items():
            if needle.lower() in query.lower():
                return [p for p in passages if p.get("score", 0.0) >= min_score]
        return []
    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)


@pytest.mark.asyncio
async def test_run_pilot_captures_coverage(monkeypatch):
    _patch(monkeypatch, {
        "energ": [{"text": "IRSE real", "source": "Data Registry · Energía",
                   "kind": "registry", "score": 9.0,
                   "meta": {"sector_key": "energy", "state": "real"}}],
    })
    report = await run_pilot(["Cómo está la resiliencia energética",
                        "Precio del cacao en Marte hoy mismo"], db=None)
    assert report.summary["n"] == 2
    assert report.rows[0].gate == "report"          # anclado a dato real
    assert report.rows[0].coverage_real == 1.0
    assert report.rows[1].gate == GATE_SCOPING       # sin evidencia → scoping
    # markdown de piloto lista ambas y deja las horas como campo a completar.
    md = report.to_markdown()
    assert "Piloto manual" in md and "h DD actual" in md
    assert report.rows[0].hours_manual_dd is None    # no se fabrica


@pytest.mark.asyncio
async def test_export_ordered_sections_report(monkeypatch):
    _patch(monkeypatch, {
        "energ": [{"text": "IRSE real", "source": "Data Registry · Energía",
                   "kind": "registry", "score": 9.0,
                   "meta": {"sector_key": "energy", "state": "real"}}],
    })
    ans = await answer_question("Cómo está la resiliencia energética del sistema", db=None)
    titles = [t for t, _ in ordered_sections(ans)]
    assert titles[0] == "Resumen ejecutivo"
    assert "Limitaciones" in titles
    md = to_markdown(ans)
    assert "SDQ · Market Intelligence" in md
    assert "Metodología" in md


@pytest.mark.asyncio
async def test_export_scoping_order(monkeypatch):
    _patch(monkeypatch, {})  # todo brecha → scoping
    ans = await answer_question("Tema completamente ausente del corpus propio", db=None)
    titles = [t for t, _ in ordered_sections(ans)]
    assert titles[0] == "Alcance"
    assert "Lo que no se puede contestar hoy" in titles


# ── El costo de IA del piloto se MIDE (antes era un 0.0 escrito a mano) ──────────
# `PilotRow.ai_cost_usd` se fijaba en 0.0 con la nota «núcleo determinista: sin costo de IA
# todavía». Dejó de ser cierta: el motor rutea dominios y juzga pertinencia con el modelo, y
# cada pregunta paga esas llamadas. Un cero escrito a mano se lee como gasto real de cero.

@pytest.mark.asyncio
async def test_el_costo_de_ia_del_piloto_es_lo_que_la_pregunta_GASTO(monkeypatch):
    """Y se atribuye POR pregunta: la segunda no hereda lo que gastó la primera."""
    import shared.research.pilot as pilot_mod
    from shared.observability.llm_ledger import PURPOSE_ROUTING, record_call

    gastos = iter([0.03, 0.005])

    async def fake_answer(question, **kw):
        record_call(purpose=PURPOSE_ROUTING, model="claude-sonnet-4-6",
                    cost_usd=next(gastos))
        return await answer_question(question, **kw)

    _patch(monkeypatch, {})
    monkeypatch.setattr(pilot_mod, "answer_question", fake_answer)
    report = await run_pilot(["Primera pregunta del piloto",
                              "Segunda pregunta del piloto"], db=None)

    assert report.rows[0].ai_cost_usd == pytest.approx(0.03)
    assert report.rows[1].ai_cost_usd == pytest.approx(0.005)
    assert report.rows[0].ai_calls == 1
    assert all(r.ai_cost_es_exacto for r in report.rows)


@pytest.mark.asyncio
async def test_un_piloto_sin_llamadas_reporta_un_cero_MEDIDO_y_lo_dice(monkeypatch):
    """Cero es una respuesta válida cuando el conteo la respalda: `ai_calls == 0` es lo que
    separa «no llamó al modelo» de «no se midió»."""
    _patch(monkeypatch, {})
    report = await run_pilot(["Pregunta sin Cerebro disponible"], db=None)
    fila = report.rows[0]
    assert (fila.ai_cost_usd, fila.ai_calls) == (0.0, 0)
    assert fila.to_dict()["ai_calls"] == 0


@pytest.mark.asyncio
async def test_una_tarifa_supuesta_marca_el_importe_del_piloto(monkeypatch):
    """El markdown no puede publicar un importe pelado si parte salió de una suposición."""
    import shared.research.pilot as pilot_mod
    from shared.observability.llm_ledger import PURPOSE_ROUTING, record_call

    async def fake_answer(question, **kw):
        record_call(purpose=PURPOSE_ROUTING, model="modelo-sin-tarifa", cost_usd=0.02)
        return await answer_question(question, **kw)

    _patch(monkeypatch, {})
    monkeypatch.setattr(pilot_mod, "answer_question", fake_answer)
    report = await run_pilot(["Pregunta con un modelo fuera del tarifario"], db=None)

    assert report.rows[0].ai_calls_sin_tarifa == 1
    assert not report.rows[0].ai_cost_es_exacto
    assert "≈0.02" in report.to_markdown()
