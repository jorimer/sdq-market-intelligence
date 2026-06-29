"""Tests del framework sector-agnóstico de productos.

Prueban que el ensamblador orquesta cualquier ``SectorProduct`` sin conocer el
sector, que el sensor de anonimización Pulse bloquea fugas, y las invariantes del
manifiesto/nivel. Usan un sector FALSO (no banking) — eso ES la prueba anti-Frankenstein:
el framework no depende de ningún módulo de sector.
"""
import asyncio
import os
import tempfile

import pytest

from shared.products import (
    AnonymizationError,
    DataHealth,
    Granularity,
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    SectorProductManifest,
    TierLevelSpec,
    ValidationState,
    assemble_product_report,
    enforce_anonymized,
    required_signal_methods,
)


# ── Sector falso que implementa el contrato (mínimo, sin DB ni PDF) ──

def _manifest() -> SectorProductManifest:
    return SectorProductManifest(
        sector_key="fake",
        display_name="Fake Sector",
        levels={
            ProductTier.pulse: TierLevelSpec(
                tier=ProductTier.pulse, granularity=Granularity.system,
                sections=("system_overview",), narrative_templates=("system_overview",),
                audience="abierto", cadence="periodic", watermark="Vista abierta",
            ),
            ProductTier.insight: TierLevelSpec(
                tier=ProductTier.insight, granularity=Granularity.named_entity,
                sections=("executive_summary",), narrative_templates=("executive_summary",),
                audience="cliente", cadence="recurring",
            ),
        },
    )


class FakeSector:
    sector_key = "fake"

    def __init__(self, leak: bool = False):
        self._leak = leak
        self.narrated = False

    def product_manifest(self):
        return _manifest()

    def data_signals(self):
        return DataHealth(coverage=1.0, freshness_days=10, sources=("FUENTE",))

    def has_engine(self):
        return True

    def validation_state(self):
        return ValidationState(approved=True, score=0.8)

    def snapshot(self, tier, period, scope=None):
        if tier == ProductTier.pulse:
            payload = {"band_distribution": {"Fuerte": 3, "Adecuado": 2}}
            if self._leak:
                payload["comment"] = "Banco Demo lidera el sistema"  # fuga deliberada
            return ProductSnapshot(tier=tier, period=period, payload=payload,
                                   entity_roster=("Banco Demo", "Otro Banco"))
        return ProductSnapshot(tier=tier, period=period,
                               payload={"score": 82.0}, entity_name="Banco Demo")

    async def narratives(self, tier, snapshot, lang="es"):
        self.narrated = True
        return {s: f"texto {s}" for s in self.product_manifest().require_level(tier).sections}

    async def render(self, tier, snapshot, narratives, *, sample=False, lang="es",
                     output_dir=None, fmt="pdf"):
        out = output_dir or tempfile.gettempdir()
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"fake_{tier.value}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"{tier.value}|sample={sample}|{list(narratives)}")
        return path


# ── Contrato ──

def test_fake_satisfies_protocol():
    assert isinstance(FakeSector(), SectorProduct)
    for m in required_signal_methods():
        assert hasattr(FakeSector(), m)


# ── Ensamblador genérico ──

def test_assemble_insight_named(tmp_path):
    sec = FakeSector()
    path = asyncio.run(assemble_product_report(
        sec, ProductTier.insight, period="2024-Q4", output_dir=str(tmp_path)))
    assert os.path.exists(path)
    assert sec.narrated is True
    assert open(path).read().startswith("insight|")


def test_assemble_pulse_system_ok(tmp_path):
    path = asyncio.run(assemble_product_report(
        FakeSector(leak=False), ProductTier.pulse, period="2024-Q4", output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_assemble_pulse_blocks_entity_leak(tmp_path):
    """Si el snapshot de sistema filtra un nombre del roster → AnonymizationError."""
    with pytest.raises(AnonymizationError):
        asyncio.run(assemble_product_report(
            FakeSector(leak=True), ProductTier.pulse, period="2024-Q4", output_dir=str(tmp_path)))


def test_assemble_system_with_entity_name_raises_anonymization(tmp_path):
    """Un nivel system con entity_name seteado es una fuga → AnonymizationError
    (no AssertionError: doctrina uniforme, no se desactiva con python -O)."""
    sec = FakeSector()
    orig = sec.snapshot

    def named_system(tier, period, scope=None):
        snap = orig(tier, period, scope)
        return ProductSnapshot(tier=snap.tier, period=snap.period, payload=snap.payload,
                               entity_name="Banco X", entity_roster=snap.entity_roster)

    sec.snapshot = named_system
    with pytest.raises(AnonymizationError):
        asyncio.run(assemble_product_report(
            sec, ProductTier.pulse, period="2024-Q4", output_dir=str(tmp_path)))


def test_assemble_unknown_tier_is_spanish_error(tmp_path):
    with pytest.raises(ValueError, match="no ofrece el nivel"):
        asyncio.run(assemble_product_report(
            FakeSector(), ProductTier.deep_dive, period="2024-Q4", output_dir=str(tmp_path)))


# ── Sensor de anonimización (unitario) ──

def test_anonymization_forbidden_key():
    with pytest.raises(AnonymizationError, match="clave reservada"):
        enforce_anonymized({"top10": [{"v": 1}]})


def test_anonymization_roster_substring():
    with pytest.raises(AnonymizationError, match="Banco Demo"):
        enforce_anonymized({"nota": "el líder es Banco Demo, S.A."},
                           entity_roster=("Banco Demo",))


def test_anonymization_clean_passes():
    enforce_anonymized({"band_distribution": {"Fuerte": 3}, "hhi": 1200},
                       entity_roster=("Banco Demo",))


# ── Invariantes de nivel/manifiesto ──

def test_pulse_must_be_system():
    with pytest.raises(ValueError, match="Pulse debe ser"):
        TierLevelSpec(tier=ProductTier.pulse, granularity=Granularity.named_entity,
                      sections=(), narrative_templates=(), audience="x", cadence="periodic")


def test_manifest_require_level_missing():
    m = _manifest()
    with pytest.raises(ValueError, match="no ofrece el nivel 'deep_dive'"):
        m.require_level(ProductTier.deep_dive)


def test_manifest_tiers_ordered():
    assert _manifest().tiers() == [ProductTier.pulse, ProductTier.insight]
