"""Pre-calentado de la caché de reportes: warmea publicados, salta no-publicados, resiste
fallos por combo, y expande los ámbitos de los niveles nombrados."""
import asyncio

import pytest

from shared.products import prewarm as pw
from shared.products.manifest import SectorProductManifest
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec


def _manifest() -> SectorProductManifest:
    return SectorProductManifest(sector_key="fake", display_name="Fake", levels={
        ProductTier.pulse: TierLevelSpec(
            tier=ProductTier.pulse, granularity=Granularity.system,
            sections=("s",), narrative_templates=("t",), audience="a", cadence="periodic"),
        ProductTier.insight: TierLevelSpec(
            tier=ProductTier.insight, granularity=Granularity.named_entity,
            sections=("s",), narrative_templates=("t",), audience="a", cadence="recurring"),
        ProductTier.deep_dive: TierLevelSpec(
            tier=ProductTier.deep_dive, granularity=Granularity.named_entity,
            sections=("s",), narrative_templates=("t",), audience="a", cadence="on_demand"),
    })


class _FakeProduct:
    sector_key = "fake"

    def product_manifest(self):
        return _manifest()

    def scope_options(self):
        return [{"value": "AAA", "label": "AAA"}, {"value": "BBB", "label": "BBB"}]


class _DummyWDB:
    """Sesión por-reporte: solo necesita cerrarse."""
    def close(self):
        pass


def _patch(monkeypatch, *, activated_tiers, calls, boom=None):
    monkeypatch.setattr(pw, "registered_sectors", lambda: ["fake"])
    monkeypatch.setattr(pw, "get_product", lambda sector, db: _FakeProduct())
    monkeypatch.setattr(pw, "SessionLocal", lambda: _DummyWDB())
    monkeypatch.setattr(
        pw, "_is_activated",
        lambda db, sector, tier: tier in activated_tiers)

    async def _fake_assemble(product, tier, *, period, scope, lang):
        key = (tier.value, scope, lang)
        calls.append(key)
        if boom and boom(key):
            raise RuntimeError("sin datos")
    monkeypatch.setattr(pw, "assemble_product_content", _fake_assemble)


def test_warms_published_named_entity_scopes(monkeypatch):
    calls = []
    _patch(monkeypatch, activated_tiers={ProductTier.insight, ProductTier.deep_dive}, calls=calls)
    res = asyncio.run(pw.prewarm_report_cache(db=None))
    # 2 niveles nombrados × 2 entidades × 1 idioma = 4 combos.
    assert res["warmed"] == 4
    assert res["skipped_unpublished"] == 0
    assert set(calls) == {
        ("insight", "AAA", "es"), ("insight", "BBB", "es"),
        ("deep_dive", "AAA", "es"), ("deep_dive", "BBB", "es")}
    # El Pulse NUNCA se precalienta (no está en _WARM_TIERS).
    assert all(t != "pulse" for t, _, _ in calls)


def test_skips_unpublished(monkeypatch):
    calls = []
    _patch(monkeypatch, activated_tiers={ProductTier.deep_dive}, calls=calls)  # solo deep_dive publicado
    res = asyncio.run(pw.prewarm_report_cache(db=None))
    assert res["warmed"] == 2                      # solo las 2 entidades del deep_dive
    assert res["skipped_unpublished"] == 1         # insight no publicado
    assert all(t == "deep_dive" for t, _, _ in calls)


def test_per_combo_error_does_not_abort(monkeypatch):
    calls = []
    _patch(monkeypatch, activated_tiers={ProductTier.deep_dive}, calls=calls,
           boom=lambda key: key[1] == "AAA")       # AAA falla, BBB debe seguir
    res = asyncio.run(pw.prewarm_report_cache(db=None))
    assert res["warmed"] == 1                       # BBB warmeó
    assert res["n_errors"] == 1 and res["errors"]   # AAA registrado, no abortó
    assert ("deep_dive", "BBB", "es") in calls


def test_multiple_langs(monkeypatch):
    calls = []
    _patch(monkeypatch, activated_tiers={ProductTier.deep_dive}, calls=calls)
    res = asyncio.run(pw.prewarm_report_cache(db=None, langs=("es", "en")))
    assert res["warmed"] == 4                        # 2 entidades × 2 idiomas
    assert res["langs"] == ["es", "en"]


def test_system_tier_uses_single_none_scope(monkeypatch):
    """Un nivel nombrado de granularidad system (p. ej. monetary_policy deep_dive) → 1 solo
    ámbito None, no el selector de entidades."""
    calls = []

    class _SystemProduct(_FakeProduct):
        def product_manifest(self):
            return SectorProductManifest(sector_key="fake", display_name="F", levels={
                ProductTier.deep_dive: TierLevelSpec(
                    tier=ProductTier.deep_dive, granularity=Granularity.system,
                    sections=("s",), narrative_templates=("t",), audience="a", cadence="on_demand"),
            })

    monkeypatch.setattr(pw, "registered_sectors", lambda: ["fake"])
    monkeypatch.setattr(pw, "get_product", lambda sector, db: _SystemProduct())
    monkeypatch.setattr(pw, "SessionLocal", lambda: _DummyWDB())
    monkeypatch.setattr(pw, "_is_activated", lambda db, sector, tier: True)

    async def _fake_assemble(product, tier, *, period, scope, lang):
        calls.append((tier.value, scope, lang))
    monkeypatch.setattr(pw, "assemble_product_content", _fake_assemble)

    res = asyncio.run(pw.prewarm_report_cache(db=None))
    assert res["warmed"] == 1 and calls == [("deep_dive", None, "es")]
