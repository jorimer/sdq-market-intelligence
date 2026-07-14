"""Test del entregable de marca (Fase 5): render PDF/DOCX desde una respuesta."""
import pytest
import os

import shared.research.decompose as decompose_mod
from shared.research.deliverable import _subject, render_deliverable
from shared.research.orchestrator import answer_question


def _patch(monkeypatch, mapping):
    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True, min_score=0.0, min_score_by_kind=None):
        for needle, passages in mapping.items():
            if needle.lower() in query.lower():
                return [p for p in passages if p.get("score", 0.0) >= min_score]
        return []
    monkeypatch.setattr(decompose_mod, "retrieve", fake_retrieve)


@pytest.mark.asyncio
async def test_render_deliverable_pdf(monkeypatch, tmp_path):
    _patch(monkeypatch, {
        "energ": [{"text": "IRSE real capacidad", "source": "Data Registry · Energía",
                   "kind": "registry", "score": 9.0,
                   "meta": {"sector_key": "energy", "state": "real"}}],
    })
    ans = await answer_question("Cómo está la resiliencia energética del sistema", db=None)
    path = render_deliverable(ans, fmt="pdf", output_dir=str(tmp_path))
    assert path.endswith(".pdf") and os.path.getsize(path) > 1000


@pytest.mark.asyncio
async def test_render_deliverable_scoping_docx(monkeypatch, tmp_path):
    _patch(monkeypatch, {})  # todo brecha → scoping
    ans = await answer_question("Tema totalmente ausente del corpus propio de SDQ", db=None)
    assert ans.gate == "scoping"
    path = render_deliverable(ans, fmt="docx", output_dir=str(tmp_path))
    assert path.endswith(".docx") and os.path.getsize(path) > 1000


def test_subject_muestra_pregunta_completa_y_acota_lo_desmesurado():
    # antes se truncaba a 110 chars (se cortaba en portada); ahora una pregunta normal va entera
    corta = ("¿Cuántas cadenas de comida rápida operan activamente en RD, cuál es la "
             "participación de mercado por marca y cómo crecieron las ventas en 3 años?")
    assert _subject(corta) == corta
    # solo lo desmesurado se acota, en frontera de palabra + elipsis
    larga = "palabra " * 200
    s = _subject(larga)
    assert s.endswith("…") and len(s) <= 481


@pytest.mark.asyncio
async def test_render_pregunta_larga_no_rompe_filename(monkeypatch, tmp_path):
    # regresión: un display_name larguísimo generaba un filename >255 chars → OSError al guardar
    _patch(monkeypatch, {})   # scoping
    q = "Estamos evaluando la expansión de una cadena de comida rápida en RD. " * 12
    ans = await answer_question(q, db=None)
    path = render_deliverable(ans, fmt="pdf", output_dir=str(tmp_path))
    assert os.path.getsize(path) > 1000
    assert len(os.path.basename(path)) <= 255
