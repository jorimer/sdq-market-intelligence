"""Tests de Macro como sector #2 (valida la receta de onboarding).

Macro implementa el contrato a nivel app (vía getters públicos) SIN modificar el
framework. Se prueba: conformidad, manifiesto, readiness desde señales reales (con DB
vacía los getters fallan limpio → cobertura 0, honesto), y render sintético.
"""
import asyncio
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.products import (
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    compute_readiness,
    get_product,
    is_implemented,
)
from app.products_macro import MacroProduct


def test_macro_registered_and_contract():
    assert is_implemented("macro")
    assert isinstance(MacroProduct(), SectorProduct)
    assert isinstance(get_product("macro", None), MacroProduct)


def test_macro_manifest_three_tiers():
    m = MacroProduct().product_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    assert "limitations" in m.require_level(ProductTier.deep_dive).sections


def test_macro_readiness_from_signals_empty_db():
    """Con DB sin tablas de macro, los getters fallan limpio → G1/G2=0 pero G3/G4
    (manifiesto) y G5 (validación) reflejan señales reales. Prueba que NO es hardcode."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    db = sessionmaker(bind=engine)()
    rep = compute_readiness(MacroProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0   # sin dato macro
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0   # manifiesto declarado
    assert rep["g5"] == 0.85                        # validación IRMP
    # readiness = 0.15*1 + 0.15*1 + 0.15*0.85 = 0.4275
    assert abs(rep["readiness"] - 0.4275) < 1e-6
    db.close()


def _factors():
    return [{"label": "Inflación", "value": 3.2, "unit": "%", "direction": "down", "reading": "moderándose"},
            {"label": "Tipo de cambio", "value": 60.1, "unit": "RD$", "direction": "up", "reading": "estable"}]


def test_macro_render_pulse_synthetic(tmp_path):
    snap = ProductSnapshot(tier=ProductTier.pulse, period="2024-Q4",
                           payload={"factors": _factors(), "n_factors": 2, "irmp_band": "Moderado"},
                           entity_name=None)
    prod = MacroProduct()
    narr = asyncio.run(prod.narratives(ProductTier.pulse, snap))
    path = asyncio.run(prod.render(ProductTier.pulse, snap, narr, sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_macro_deep_dive_has_limitations(tmp_path):
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2024-Q4",
                           payload={"irmp_score": 38.3, "irmp_band": "Moderado", "factors": _factors()},
                           entity_name="República Dominicana")
    prod = MacroProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "IRMP" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr, output_dir=str(tmp_path)))
    assert os.path.exists(path)
