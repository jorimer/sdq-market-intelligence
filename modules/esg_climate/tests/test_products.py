"""Tests de ESG & Climate (IRC) como SectorProduct — sector #10.

Mono-módulo: implementa el contrato en el propio módulo SIN tocar el framework.
Cubren: conformidad, manifiesto, readiness desde señales reales (DB vacía/sin
tablas → G1/G2 bajan = NO hardcode), snapshot nacional anonimizado (RD, panel como
pares sin nombrar), render sintético y contrato del guard (templates thin).
"""
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import (
    ProductSnapshot,
    ProductTier,
    SectorProduct,
    assemble_product_report,
    compute_readiness,
    get_product,
    is_implemented,
)
from shared.settings.models import AppSetting  # noqa: F401 — registra tabla (validation_state)
from modules.esg_climate.models.models import ESGScore
from modules.esg_climate.products import ESGProduct, esg_manifest


def test_esg_registered_and_contract():
    assert is_implemented("esg")
    assert isinstance(ESGProduct(), SectorProduct)
    assert isinstance(get_product("esg", None), ESGProduct)


def test_esg_manifest_three_tiers():
    m = esg_manifest()
    assert m.tiers() == [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
    assert m.require_level(ProductTier.pulse).granularity.value == "system"
    dd = set(m.require_level(ProductTier.deep_dive).sections)
    assert {"panel_position", "recommendation", "limitations"} <= dd


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[ESGScore.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_panel(db):
    """RD + 2 pares con dimensiones reales (sources=live) para un período."""
    def _bd(live=True):
        src = {v: ("live" if live else "rubric")
               for v in ("climate_sensitivity", "adaptation_readiness", "governance_quality",
                         "hurricane_exposure", "fossil_dependence", "carbon_intensity")}
        dims = {"physical_risk": {"score": 40.0, "weight": 0.3, "contribution": 12.0},
                "transition_risk": {"score": 55.0, "weight": 0.2, "contribution": 11.0},
                "adaptive_capacity": {"score": 48.0, "weight": 0.3, "contribution": 14.4},
                "governance": {"score": 50.0, "weight": 0.2, "contribution": 10.0}}
        return {"dimensions": dims, "sources": src}
    db.add(ESGScore(entity_key="DOM", period="2023", esg_score=35.65, band="Baja",
                    breakdown=_bd(), model_version="2.0"))
    db.add(ESGScore(entity_key="CRI", period="2023", esg_score=62.0, band="Media",
                    breakdown=_bd(), model_version="2.0"))
    db.add(ESGScore(entity_key="HTI", period="2023", esg_score=20.0, band="Crítica",
                    breakdown=_bd(), model_version="2.0"))
    db.commit()


def test_esg_readiness_empty_db(db):
    rep = compute_readiness(ESGProduct(db), ProductTier.insight)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    assert rep["g3"] == 1.0 and rep["g4"] == 1.0
    assert rep["g5"] == 0.75  # Gate E firmado (fallback)


def test_esg_readiness_no_tables_does_not_crash():
    """Robustez (lección Macro): sin tablas, lecturas en SAVEPOINT revierten limpio."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    s = sessionmaker(bind=engine)()
    rep = compute_readiness(ESGProduct(s), ProductTier.pulse)
    assert rep["g1"] == 0.0 and rep["g2"] == 0.0
    s.close()


def test_esg_readiness_with_data(db):
    _seed_panel(db)
    rep = compute_readiness(ESGProduct(db), ProductTier.pulse)
    assert rep["g1"] > 0.0 and rep["g2"] == 1.0  # cobertura real (live) + motor


def test_esg_pulse_snapshot_is_anonymous(db):
    _seed_panel(db)
    snap = ESGProduct(db).snapshot(ProductTier.pulse, "2023")
    assert snap.entity_name is None and snap.entity_roster == ()
    assert snap.payload["rank"] == 2 and snap.payload["n_countries"] == 3  # RD 2º de 3


def test_esg_named_snapshot_is_chosen_country(db):
    _seed_panel(db)
    # País elegido (Costa Rica), NO RD prestado.
    snap = ESGProduct(db).snapshot(ProductTier.deep_dive, "2023", scope="CRI")
    assert snap.entity_name == "Costa Rica"
    assert snap.payload["score"]["entity_key"] == "CRI"
    assert snap.payload["score"]["esg_score"] == 62.0
    assert snap.payload["position"]["rank"] == 1          # CRI(62) > DOM(35.65) > HTI(20)


def test_esg_named_snapshot_requires_scope(db):
    _seed_panel(db)
    with pytest.raises(ValueError, match="país"):
        ESGProduct(db).snapshot(ProductTier.insight, "2023", scope=None)


def test_esg_scope_options_lists_scored_countries(db):
    _seed_panel(db)
    p = ESGProduct(db)
    assert p.scope_kind() == "country"
    opts = p.scope_options()
    isos = {o["value"] for o in opts}
    assert isos == {"DOM", "CRI", "HTI"}                  # solo países con IRC
    do = next(o for o in opts if o["value"] == "DOM")
    assert do["label"] == "República Dominicana" and do["group"] == "caribe"
    cr = next(o for o in opts if o["value"] == "CRI")
    assert cr["group"] == "centroamerica"


def test_esg_pulse_assemble_and_render(db, tmp_path):
    _seed_panel(db)
    path = asyncio.run(assemble_product_report(
        ESGProduct(db), ProductTier.pulse, period="2023", output_dir=str(tmp_path)))
    assert os.path.exists(path) and path.endswith(".pdf")


def test_esg_deep_dive_render_synthetic(tmp_path):
    score = {"entity_key": "DOM", "period": "2023", "esg_score": 35.65, "band": "Baja",
             "breakdown": {"dimensions": {
                 "physical_risk": {"score": 40.0, "weight": 0.3, "contribution": 12.0},
                 "governance": {"score": 50.0, "weight": 0.2, "contribution": 10.0}},
                 "sources": {"governance_quality": "live"}}}
    snap = ProductSnapshot(tier=ProductTier.deep_dive, period="2023",
                           payload={"has_score": True, "score": score,
                                    "position": {"rank": 22, "n_countries": 24,
                                                 "distribution": {"mean": 48.0, "max": 70.0, "min": 20.0}}},
                           entity_name="República Dominicana")
    prod = ESGProduct()
    narr = asyncio.run(prod.narratives(ProductTier.deep_dive, snap))
    assert "limitations" in narr and "IRC" in narr["limitations"]
    path = asyncio.run(prod.render(ProductTier.deep_dive, snap, narr,
                                   sample=True, output_dir=str(tmp_path)))
    assert os.path.exists(path)


def test_esg_templates_are_guarded():
    from shared.narrative.claude_engine import THIN_TEMPLATES
    from shared.narrative.cerebro import AXIS_DOCTRINE
    m = esg_manifest()
    assert "esg_climate" in AXIS_DOCTRINE
    for tier in m.tiers():
        for tmpl in m.require_level(tier).narrative_templates:
            assert tmpl in THIN_TEMPLATES, f"{tmpl} no es thin → sin guard"


def test_esg_no_data_narratives_are_honest():
    snap = ProductSnapshot(tier=ProductTier.insight, period="—",
                           payload={"has_score": False}, entity_name="República Dominicana")
    narr = asyncio.run(ESGProduct().narratives(ProductTier.insight, snap))
    assert all(v for v in narr.values())
