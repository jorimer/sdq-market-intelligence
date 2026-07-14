"""Tests del umbral de ancla POR-KIND en retrieve() — A4.1 del gate de honestidad.

docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md §A.4 A4.1: la doctrina/metodología (texto libre)
exige un score MÁS ALTO que el dato estructurado (registry) para anclar."""
import sys

from shared.knowledge.models import Passage
from shared.knowledge.retrieve import retrieve

# `shared.knowledge.__init__` hace `from ...retrieve import retrieve`, lo que sombrea el
# submódulo como atributo del paquete → se obtiene el módulo real vía sys.modules.
retrieve_mod = sys.modules["shared.knowledge.retrieve"]


class _FakeIndex:
    """Índice que devuelve pasajes fijos con score, ignorando el min_score base (lo aplica
    retrieve tras el search). Reemplaza a build_index en los tests."""

    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=5, min_score=0.0):
        return [(p, s) for p, s in self._hits if s >= min_score][:top_k]


def _patch_index(monkeypatch, hits):
    monkeypatch.setattr(retrieve_mod, "build_index", lambda **kw: _FakeIndex(hits))


def _p(kind, ref="r"):
    return Passage(text=f"pasaje {kind}", source=f"Fuente {kind}", kind=kind, ref=ref)


def test_by_kind_drops_doctrine_below_soft_keeps_registry(monkeypatch):
    # doctrine 8.0 (< soft 10) se descarta; registry 8.0 (≥ base 7) se conserva.
    _patch_index(monkeypatch, [(_p("registry"), 8.0), (_p("doctrine"), 8.0)])
    out = retrieve("q", db=None, min_score=7.0,
                   min_score_by_kind={"doctrine": 10.0, "methodology": 10.0})
    kinds = [r["kind"] for r in out]
    assert "registry" in kinds
    assert "doctrine" not in kinds


def test_by_kind_keeps_doctrine_above_soft(monkeypatch):
    _patch_index(monkeypatch, [(_p("doctrine"), 11.0)])
    out = retrieve("q", db=None, min_score=7.0, min_score_by_kind={"doctrine": 10.0})
    assert [r["kind"] for r in out] == ["doctrine"]


def test_by_kind_offtopic_threshold_drops_midscore_doctrine(monkeypatch):
    # A4.3: umbral off-topic (14) descarta una doctrina de score 11 que sí pasaría el soft.
    _patch_index(monkeypatch, [(_p("doctrine"), 11.0)])
    out = retrieve("q", db=None, min_score=7.0, min_score_by_kind={"doctrine": 14.0})
    assert out == []


def test_no_by_kind_is_backward_compatible(monkeypatch):
    # Sin min_score_by_kind, se comporta como antes (solo min_score base).
    _patch_index(monkeypatch, [(_p("doctrine"), 8.0), (_p("registry"), 8.0)])
    out = retrieve("q", db=None, min_score=7.0)
    assert len(out) == 2
