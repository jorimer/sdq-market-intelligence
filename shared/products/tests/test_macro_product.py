"""Tests de Macro como sector #2 (valida la receta de onboarding).

Macro implementa el contrato a nivel app (vía getters públicos) SIN modificar el
framework. Se prueba: conformidad, manifiesto, readiness desde señales reales (con DB
vacía los getters fallan limpio → cobertura 0, honesto), y render sintético.
"""
import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    compute_readiness,
    get_product,
    is_implemented,
)
from modules.macro_political_risk.models.models import (
    Country,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
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


def test_macro_narratives_are_guarded(monkeypatch):
    """Sensor guard §5: toda sección con cifras narra por un template thin + axis en
    doctrina → numeric_guard. 'recommendation' NO es thin: debe enrutarse por el thin del
    eje (risk_assessment), nunca por un template homónimo (caería a la ruta legacy sin
    guard). Regresión de task_fcc7a6b3 (bug latente destapado en P4-trade)."""
    from shared.narrative import claude_engine
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE

    calls = []

    class _Res:
        text = "ok"

    async def _fake_generate(*, context, template, mode, axis, audience):
        calls.append((template, axis))
        return _Res()

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2024-Q4",
                           payload={"irmp_score": 38.3, "irmp_band": "Moderado", "factors": _factors()},
                           entity_name="República Dominicana")
    asyncio.run(MacroProduct().narratives(ProductTier.deep_dive, snap))
    assert calls, "se esperaba al menos una sección con cifras narrada"
    for template, axis in calls:
        assert template in THIN_TEMPLATES, f"{template} no es thin → narraría sin guard"
        assert axis in AXIS_DOCTRINE, f"{axis} sin doctrina → sin guard"
    # La recomendación NO debe enrutarse por el template no-thin 'recommendation'.
    assert "recommendation" not in {t for t, _ in calls}


@pytest.fixture()
def db():
    """DB en memoria con el panel IRMP sembrado (RD + 2 pares, 1 período)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Country.__table__, IRMPSnapshot.__table__,
                                             DimensionScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _bd():
    return {"political": {"score": 32.0, "weight": 0.25, "contribution": 8.0},
            "macro": {"score": 52.0, "weight": 0.25, "contribution": 13.0},
            "external": {"score": 40.0, "weight": 0.20, "contribution": 8.0}}


def _seed_panel(db):
    per = date(2024, 12, 31)
    rows = [("DO", "República Dominicana", "Caribe", 38.3, RiskBand.moderado),
            ("JM", "Jamaica", "Caribe", 36.3, RiskBand.alto),
            ("CR", "Costa Rica", "Centroamérica", 64.9, RiskBand.moderado)]
    for iso, name, region, score, band in rows:
        c = Country(iso_code=iso, name=name, region=region, is_active=True)
        db.add(c)
        db.flush()
        db.add(IRMPSnapshot(country_id=c.id, period_end=per, irmp_score=score,
                            risk_band=band, peer_set_size=3, breakdown=_bd()))
    db.commit()


def test_macro_scope_options_lists_scored_countries(db):
    _seed_panel(db)
    opts = MacroProduct(db).scope_options()
    assert MacroProduct(db).scope_kind() == "country"
    isos = {o["value"] for o in opts}
    assert isos == {"DO", "JM", "CR"}                 # solo países con snapshot
    do = next(o for o in opts if o["value"] == "DO")
    assert do["label"] == "República Dominicana" and do["group"] == "caribe"
    cr = next(o for o in opts if o["value"] == "CR")
    assert cr["group"] == "centroamerica"             # región → slug i18n


def test_macro_named_snapshot_is_chosen_country(db):
    _seed_panel(db)
    snap = MacroProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope="JM")
    assert snap.entity_name == "Jamaica"              # país elegido, NO RD prestado
    assert snap.payload["country_code"] == "JM"
    assert snap.payload["irmp_score"] == 36.3
    assert snap.payload["dimensions"]                 # breakdown del país


def test_macro_deep_dive_has_peer_position(db):
    _seed_panel(db)
    snap = MacroProduct(db).snapshot(ProductTier.deep_dive, "2024-12-31", scope="DO")
    pos = snap.payload["peer_position"]
    assert pos["n_countries"] == 3
    assert pos["rank"] == 2                            # CR(64.9) > DO(38.3) > JM(36.3)
    assert pos["distribution"]["max"] == 64.9


def test_macro_named_snapshot_requires_scope(db):
    _seed_panel(db)
    with pytest.raises(ValueError, match="país"):
        MacroProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope=None)


def test_macro_unknown_country_raises(db):
    _seed_panel(db)
    with pytest.raises(ValueError, match="IRMP"):
        MacroProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope="ZZ")


def test_macro_pulse_is_anonymous():
    """Sensor anonimización §5: el Pulse macro es nacional/agregado — nunca nombra
    entidad (entity_name None) y su payload pasa el enforce del framework."""
    from shared.products.anonymization import enforce_anonymized
    m = MacroProduct().product_manifest()
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    snap = ProductSnapshot(tier=ProductTier.pulse, period="2024-Q4",
                           payload={"factors": _factors(), "n_factors": 2, "irmp_band": "Moderado"},
                           entity_name=None)
    assert snap.entity_name is None
    enforce_anonymized(snap.payload, entity_roster=snap.entity_roster)  # no debe levantar
