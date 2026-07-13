"""Degradación de nivel en el pull del motor (hallazgo del piloto Fase 2, 2026-07-13).

Un motor puede declarar "sin dato" en un nivel de dos formas: lanzando (banca/pensiones)
o devolviendo ``{"has_data": False}`` (seguros pre-fix). ``pull_axis`` debe tratar AMBAS
como ausencia y degradar al siguiente nivel — el bug real: el dict no-vacío cortaba la
cadena deep_dive→insight→pulse y el eje insurance salía como "has_data False" en vez de
las primas reales del Pulse.
"""
from types import SimpleNamespace

import shared.research.data_pull as dp
from shared.products.contract import ProductSnapshot
from shared.products.tiers import ProductTier
from shared.research.resolve import ResolvedEntity


class _StubInsuranceProduct:
    """Reproduce la forma pre-fix del motor de seguros: niveles nombrados sin scope
    devuelven ``has_data: False`` (no lanzan); el Pulse trae el mercado real."""

    def snapshot(self, tier, period, scope=None):
        if tier == ProductTier.pulse:
            return ProductSnapshot(
                tier=tier, period="2026-03",
                payload={"has_data": True,
                         "pulse": {"has_data": True, "total_premiums_rd": 153_358_565_550.53,
                                   "growth_pct": 15.3, "top4_concentration_pct": 87.1,
                                   "active_insurers": 26}},
                entity_name=None)
        return ProductSnapshot(tier=tier, period=period or "—",
                               payload={"has_data": False}, entity_name=None)


class _FakeSession:
    def rollback(self):  # pragma: no cover — no debería invocarse en estos tests
        pass


def test_pull_axis_degrades_past_has_data_false(monkeypatch):
    monkeypatch.setattr(dp, "get_product", lambda key, db: _StubInsuranceProduct())
    pull = dp.pull_axis(_FakeSession(), "insurance")
    assert pull.ok, f"el eje no ancló: note={pull.note!r}"
    assert pull.payload.get("has_data") is True
    assert pull.period == "2026-03"
    texts = " || ".join(e.text for e in pull.evidence)
    assert "153,358,565,551" in texts        # primas reales del Pulse, no relleno
    assert "has_data" not in texts           # el bool jamás es "evidencia"


def test_pull_entity_degrades_to_gap_on_has_data_false(monkeypatch):
    monkeypatch.setattr(dp, "get_product", lambda key, db: _StubInsuranceProduct())
    resolved = ResolvedEntity(sector_key="insurance", label="Aseguradora X",
                              scope_value="aseguradora_x")
    pull = dp.pull_entity(_FakeSession(), resolved)
    assert not pull.ok                       # brecha honesta, no evidencia fabricada
    assert "Sin dato del motor" in pull.note
    assert not pull.evidence


def test_generic_summary_ignores_bools():
    evs = dp._generic_summary("SDQ Seguros (SIS)", {"has_data": False}, None, "SIS")
    texts = " || ".join(e.text for e in evs)
    assert "has_data" not in texts
