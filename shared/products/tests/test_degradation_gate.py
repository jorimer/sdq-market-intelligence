"""Gate de degradación en el ensamblado de productos (anti Deep-Dive hueco).

Reproduce el defecto original (seguros/pensiones 2026-07-27): con la narrativa IA degradada
a fallback estático, un producto premium se ensamblaba y se ENTREGABA igual — un PDF de ~5k
que dice "El análisis ampliado se incorpora en la versión completa del producto". Estos tests
fijan el contrato del choke point ``_content_from_snapshot``:

  * PREMIUM (nombrado: Insight/Deep Dive) con ≥1 sección de análisis degradada → lanza
    ``NarrativeDegradedError`` (no se entrega).
  * PULSE (sistema/abierto) → solo se registra; no rompe la entrega.
  * La caché de narrativas NUNCA persiste texto degradado (si no, el hueco sobreviviría al
    outage).
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.narrative.claude_engine import (
    STATIC_FALLBACK_GENERIC,
    NarrativeDegradedError,
    is_static_fallback_text,
)
from shared.products import (
    Granularity,
    ProductTier,
    SectorProductManifest,
    TierLevelSpec,
)
from shared.products.assembler import _content_from_snapshot, _narratives_cached
from shared.products.contract import ProductSnapshot
from shared.products.models import ProductReportCache  # noqa: F401 — registra la tabla

_SECTIONS = ("assessment", "peer_positioning", "recommendation")


class _Product:
    """Producto mínimo que respeta el contrato real: devuelve ``{sección: texto}`` (descarta
    ``model_used``, como los products.py reales). ``degraded`` fuerza fallback estático."""

    sector_key = "insurance"

    def __init__(self, granularity, tier, degraded, db=None):
        self._gran, self._tier, self._degraded, self._db = granularity, tier, degraded, db
        self.calls = 0

    def product_manifest(self):
        return SectorProductManifest(
            sector_key=self.sector_key, display_name="Fake", levels={
                self._tier: TierLevelSpec(
                    tier=self._tier, granularity=self._gran, sections=_SECTIONS,
                    narrative_templates=(), audience="x", cadence="on_demand",
                    price_band="x")})

    async def narratives(self, tier, snapshot, lang="es"):
        self.calls += 1
        if self._degraded:
            return {s: STATIC_FALLBACK_GENERIC for s in _SECTIONS}
        return {s: f"Prosa real de análisis para {s}." for s in _SECTIONS}


def _snap(tier, entity):
    return ProductSnapshot(tier=tier, period="2025", payload={"has_data": True},
                           entity_name=entity)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ProductReportCache.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_premium_deep_dive_with_degraded_narrative_raises():
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=True)
    with pytest.raises(NarrativeDegradedError) as ei:
        asyncio.run(_content_from_snapshot(
            p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Seguros Reservas"),
            "es", scope="sr"))
    assert set(ei.value.sections) == set(_SECTIONS)  # las 3 de análisis, no metodología/fuentes


def test_premium_insight_with_single_degraded_section_raises():
    """Umbral = 1: una sola sección de análisis degradada ya invalida un premium."""
    class _OneBad(_Product):
        async def narratives(self, tier, snapshot, lang="es"):
            return {"assessment": STATIC_FALLBACK_GENERIC,
                    "peer_positioning": "Prosa real.",
                    "recommendation": "Prosa real."}
    p = _OneBad(Granularity.named_entity, ProductTier.insight, degraded=True)
    with pytest.raises(NarrativeDegradedError) as ei:
        asyncio.run(_content_from_snapshot(
            p, ProductTier.insight, _snap(ProductTier.insight, "AFP X"), "es", scope="x"))
    assert ei.value.sections == ["assessment"]


def test_premium_deep_dive_healthy_narrative_assembles():
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=False)
    content = asyncio.run(_content_from_snapshot(
        p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Seguros Reservas"),
        "es", scope="sr"))
    assert not any(is_static_fallback_text(content.narratives[s]) for s in _SECTIONS)


def test_open_pulse_with_degraded_narrative_does_not_raise():
    """El Pulse (sistema/abierto) tolera la degradación: se registra, no rompe la entrega."""
    p = _Product(Granularity.system, ProductTier.pulse, degraded=True)
    content = asyncio.run(_content_from_snapshot(
        p, ProductTier.pulse, _snap(ProductTier.pulse, None), "es", scope=None))
    assert all(is_static_fallback_text(content.narratives[s]) for s in _SECTIONS)


def test_degraded_narratives_are_not_cached(db):
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=True, db=db)
    snap = _snap(ProductTier.deep_dive, "Seguros Reservas")
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "sr"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "sr"))
    assert db.query(ProductReportCache).count() == 0   # nunca se persiste el hueco
    assert p.calls == 2                                 # sin HIT → regenera (reintenta)


@pytest.fixture()
def bus_events():
    """Captura los NARRATIVE_DEGRADED publicados; deja el bus limpio antes y después."""
    from shared.events.event_bus import NARRATIVE_DEGRADED, event_bus
    event_bus.clear()
    captured = []
    event_bus.subscribe(NARRATIVE_DEGRADED, captured.append)
    try:
        yield captured
    finally:
        event_bus.clear()


def test_premium_degradation_emits_blocked_event(bus_events):
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=True)
    with pytest.raises(NarrativeDegradedError):
        asyncio.run(_content_from_snapshot(
            p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Seguros Reservas"),
            "es", scope="sr"))
    assert len(bus_events) == 1
    ev = bus_events[0]
    assert ev["surface"] == "products" and ev["tier"] == "deep_dive"
    assert ev["blocked"] is True
    assert set(ev["sections"]) == set(_SECTIONS) and ev["section_count"] == len(_SECTIONS)
    assert ev["scope"] == "sr"


def test_open_pulse_degradation_emits_non_blocked_event(bus_events):
    p = _Product(Granularity.system, ProductTier.pulse, degraded=True)
    asyncio.run(_content_from_snapshot(
        p, ProductTier.pulse, _snap(ProductTier.pulse, None), "es", scope=None))
    assert len(bus_events) == 1
    assert bus_events[0]["blocked"] is False and bus_events[0]["tier"] == "pulse"


def test_healthy_narrative_emits_no_event(bus_events):
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=False)
    asyncio.run(_content_from_snapshot(
        p, ProductTier.deep_dive, _snap(ProductTier.deep_dive, "Seguros Reservas"),
        "es", scope="sr"))
    assert bus_events == []


def test_default_ops_subscriber_logs_blocked_alert(caplog):
    """El suscriptor de ops por defecto deja un registro estructurado (error si bloqueado)."""
    import logging
    from shared.events.event_bus import event_bus
    from shared.narrative.degradation_events import subscribe_narrative_degradation_events
    event_bus.clear()
    subscribe_narrative_degradation_events()
    try:
        with caplog.at_level(logging.WARNING, logger="sdq.narrative.degradation"):
            from shared.narrative.degradation_events import emit_narrative_degraded
            emit_narrative_degraded(surface="products", sector_key="insurance",
                                    tier="deep_dive", sections=["assessment"], blocked=True,
                                    scope="sr", period="2025")
        assert any("ENTREGA BLOQUEADA" in r.getMessage() for r in caplog.records)
        assert any(r.levelno == logging.ERROR for r in caplog.records)  # bloqueado = error
    finally:
        event_bus.clear()


def test_healthy_narratives_are_cached(db):
    p = _Product(Granularity.named_entity, ProductTier.deep_dive, degraded=False, db=db)
    snap = _snap(ProductTier.deep_dive, "Seguros Reservas")
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "sr"))
    asyncio.run(_narratives_cached(p, ProductTier.deep_dive, snap, "es", "sr"))
    assert db.query(ProductReportCache).count() == 1   # limpio se cachea
    assert p.calls == 1                                 # 2º fue HIT
