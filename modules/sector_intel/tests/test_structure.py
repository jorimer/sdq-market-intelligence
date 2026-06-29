"""Tests de la estructura sectorial agregada (peso + contribución al crecimiento)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.sector_intel.models.models import SectorVariable
from modules.sector_intel.scoring.structure import compute_economic_structure
from modules.sector_intel.service import get_economic_structure


def test_contribution_distinguishes_size_from_growth():
    # construcción: grande (13%) pero se contrae (−2) → RESTA; financiero: mediano (5%)
    # y crece fuerte (+8) → APORTA más que comercio (grande pero plano).
    sectors = {
        "construccion": {"sector_size": 13.0, "sector_growth": -2.0},
        "financiero": {"sector_size": 5.0, "sector_growth": 8.0},
        "comercio": {"sector_size": 12.0, "sector_growth": 1.0},
    }
    names = {"construccion": "Construcción", "financiero": "Financiero", "comercio": "Comercio"}
    r = compute_economic_structure(sectors, names)
    # contribuciones: construcción −0.26, financiero +0.40, comercio +0.12
    contrib = {s["slug"]: s["contribution"] for s in r["sectors"]}
    assert contrib["construccion"] == pytest.approx(-0.26)
    assert contrib["financiero"] == pytest.approx(0.40)
    # ranking por peso: construcción (13) primero
    assert r["sectors"][0]["slug"] == "construccion"
    # motores ordenados por aporte: financiero primero; construcción es lastre
    assert r["drivers"][0]["slug"] == "financiero"
    assert r["top_drag"]["slug"] == "construccion"
    # crecimiento agregado = suma de contribuciones
    assert r["total_va_growth"] == pytest.approx(-0.26 + 0.40 + 0.12)
    assert r["coverage"] == pytest.approx(0.30, abs=1e-6)  # 30% del VAB representado


def test_missing_growth_is_honest():
    # un sector sin crecimiento no acredita contribución, pero sí pesa en estructura
    sectors = {
        "turismo": {"sector_size": 9.0, "sector_growth": 3.0},
        "nuevo": {"sector_size": 5.0, "sector_growth": None},
    }
    r = compute_economic_structure(sectors, {})
    slugs = {s["slug"]: s for s in r["sectors"]}
    assert slugs["nuevo"]["contribution"] is None
    assert slugs["nuevo"]["weight"] == 5.0  # cuenta en estructura
    # solo turismo aporta a la contribución
    assert r["contribution_coverage"] == pytest.approx(0.09, abs=1e-6)
    assert r["total_va_growth"] == pytest.approx(0.27)


def test_empty():
    r = compute_economic_structure({}, {})
    assert r["sectors"] == [] and r["total_va_growth"] == 0.0
    assert r["coverage"] == 0.0 and r["concentration_hhi"] is None


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SectorVariable.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_get_economic_structure_reads_real_inputs(db):
    # siembra si_variables (dimension="sector") como lo hace bcrd-sectores-sync
    rows = [
        ("turismo", "sector_size", 8.94), ("turismo", "sector_growth", 3.5),
        ("construccion", "sector_size", 13.45), ("construccion", "sector_growth", -1.8),
    ]
    for sc, var, val in rows:
        db.add(SectorVariable(sector_code=sc, dimension="sector", variable=var,
                              period="2025", value=val))
    db.commit()
    st = get_economic_structure(db)
    assert st["has_data"] and st["period"] == "2025"
    contrib = {s["slug"]: s["contribution"] for s in st["sectors"]}
    assert contrib["turismo"] == pytest.approx(0.313, abs=1e-3)
    assert contrib["construccion"] == pytest.approx(-0.242, abs=1e-3)
    # turismo es motor, construcción lastre
    assert st["top_driver"]["slug"] == "turismo"
    assert st["top_drag"]["slug"] == "construccion"
    # nombres resueltos vía catálogo BCRD
    assert "Turismo" in st["top_driver"]["name"]
