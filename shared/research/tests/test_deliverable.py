"""Test del entregable de marca (Fase 5): render PDF/DOCX desde una respuesta."""
import pytest
import os

import shared.research.decompose as decompose_mod
from shared.research.deliverable import render_deliverable
from shared.research.orchestrator import answer_question


def _patch(monkeypatch, mapping):
    def fake_retrieve(query, top_k=5, *, db=None, include_registry=True, min_score=0.0):
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
