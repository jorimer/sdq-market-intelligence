"""Integración del glosario automático en el punto único del ensamblador.

`_content_from_snapshot` es el núcleo compartido de la vista in-app y el PDF/Word:
si el glosario entra ahí, lo heredan los 15+ módulos de sector sin tocar cada uno.
"""
import asyncio

from shared.products.contract import ProductSnapshot
from shared.products.manifest import SectorProductManifest
from shared.products.report_sections import GLOSSARY_KEY, METHODOLOGY_KEY
from shared.products.tiers import Granularity, ProductTier, TierLevelSpec


class _FakeProduct:
    """Producto mínimo del contrato: manifiesto + narrativas fijas (sin motor IA, sin DB)."""

    sector_key = "fake"

    def __init__(self, narrative_text: str):
        self._text = narrative_text

    def product_manifest(self) -> SectorProductManifest:
        def spec(tier):
            return TierLevelSpec(
                tier=tier, granularity=Granularity.named_entity,
                sections=("executive_summary",), narrative_templates=("executive_summary",),
                audience="test", cadence="on_demand")
        return SectorProductManifest(
            sector_key="fake", display_name="Fake",
            levels={t: spec(t) for t in (ProductTier.insight, ProductTier.deep_dive)})

    async def narratives(self, tier, snapshot, lang):
        return {"executive_summary": self._text}

    def data_signals(self):
        return None

    def validation_state(self):
        return None


def _content(product, tier):
    from shared.products.assembler import _content_from_snapshot
    snapshot = ProductSnapshot(tier=tier, period="2026-Q2", payload={},
                               entity_name="Entidad Test")
    return asyncio.run(_content_from_snapshot(product, tier, snapshot, "es"))


def test_deep_dive_gets_glossary_with_terms_used():
    content = _content(_FakeProduct("El ROA mejora mientras el HHI del mercado baja."),
                       ProductTier.deep_dive)
    assert GLOSSARY_KEY in content.narratives
    md = content.narratives[GLOSSARY_KEY]
    assert "- **ROA**" in md and "- **HHI**" in md
    # Solo los términos que ESTE texto usa — nada de volcado completo del catálogo.
    assert "- **ISF**" not in md
    # El orden de secciones incluye el glosario (antes de las std de metodología).
    assert GLOSSARY_KEY in content.section_order
    assert content.section_order.index(GLOSSARY_KEY) < content.section_order.index(METHODOLOGY_KEY)


def test_no_glossary_section_when_text_has_no_terms():
    content = _content(_FakeProduct("Prosa sin jerga del catálogo."), ProductTier.insight)
    assert GLOSSARY_KEY not in content.narratives
    assert GLOSSARY_KEY not in content.section_order
