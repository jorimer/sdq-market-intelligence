"""Tests del path ITU DataHub (fuente vigente de telecom; INDOTEL congelado 2022-Q1).

Nunca toca la red: ``parse_indicators`` sobre un by_code fijo + scoring + persist + la
frescura ANUAL del producto.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.itu_client import (
    CODE_FIXED_BROADBAND,
    CODE_HH_INTERNET,
    CODE_MOBILE,
    CODE_MOBILE_BROADBAND,
    CODE_POPULATION,
    parse_indicators,
)
from modules.telecom_intel.models.models import TelecomScore
from modules.telecom_intel.products import TelecomProduct
from modules.telecom_intel.scoring.penetration import compute_telecom_index_itu
from modules.telecom_intel.service import compute_and_persist_itu, get_latest

# by_code fijo (estructura real de la API v2): conteos móvil/banda-ancha-móvil + per-100
# de banda ancha fija + % hogares + población. 2024 es el año más reciente con dato móvil.
BY_CODE = {
    CODE_POPULATION: {2023: 11_331_265.0, 2024: 11_427_557.0},
    CODE_MOBILE: {2023: 10_400_000.0, 2024: 10_708_716.0},
    CODE_MOBILE_BROADBAND: {2023: 8_200_000.0, 2024: 8_692_827.0},
    CODE_FIXED_BROADBAND: {2023: 10.9, 2024: 11.2},
    CODE_HH_INTERNET: {2024: 58.3},
}


def test_parse_indicators_derives_penetration():
    ind = parse_indicators(BY_CODE)
    assert ind["period"] == "2024"
    assert ind["mobile_penetration"] == pytest.approx(93.7, abs=0.2)         # 10.71M/11.43M×100
    assert ind["mobile_broadband_penetration"] == pytest.approx(76.1, abs=0.2)
    assert ind["fixed_broadband_penetration"] == 11.2                        # ya per-100
    assert ind["households_internet"] == 58.3
    assert ind["population"] == 11_427_557


def test_parse_empty_is_honest():
    ind = parse_indicators({})
    assert ind["period"] is None and ind["mobile_penetration"] is None


def test_compute_idt_itu_full_coverage():
    idx = compute_telecom_index_itu(93.7, 76.1, 11.2, households_internet=58.3)
    assert idx["coverage"] == 1.0
    assert idx["band"] in {"Fuerte", "Adecuado", "Vigilancia", "Crítico"}
    # 0.30·93.7 + 0.40·76.1 + 0.30·11.2 = 61.91
    assert idx["telecom_score"] == pytest.approx(61.91, abs=0.1)
    assert idx["dimensions"]["internet_penetration"]["score"] == 76.1


def test_compute_idt_itu_partial_weights_present_only():
    idx = compute_telecom_index_itu(90.0, None, 10.0)
    # solo móvil (0.30) + fija (0.30) → cobertura 0.6, score = media ponderada de las 2
    assert idx["coverage"] == pytest.approx(0.6, abs=1e-6)
    assert idx["telecom_score"] == pytest.approx(50.0, abs=0.1)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[TelecomScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _itu_indicators():
    return {"period": "2024", "mobile_penetration": 93.7,
            "mobile_broadband_penetration": 76.1, "fixed_broadband_penetration": 11.2,
            "households_internet": 58.3, "population": 11_427_557}


def test_compute_and_persist_itu(db):
    res = compute_and_persist_itu(db, indicators=_itu_indicators())
    assert res["period"] == "2024" and res["band"] == "Adecuado"
    row = get_latest(db)
    assert row.mobile_penetration == 93.7 and row.internet_penetration == 76.1
    assert row.broadband_share == 11.2 and row.coverage == 1.0


def test_product_freshness_annual_for_itu_period(db):
    compute_and_persist_itu(db, indicators=_itu_indicators())
    sig = TelecomProduct(db).data_signals()
    assert sig.cadence == "annual" and sig.sources == ("ITU DataHub",)
    assert sig.coverage == 1.0
    assert sig.freshness_days is not None and sig.freshness_days < 730  # anual fresco


# ── parse_indicators_for_year: exact-year, sin arrastrar el futuro ──────────────

def test_parse_for_year_uses_exact_year_not_future():
    from shared.data.itu_client import parse_indicators_for_year
    ind = parse_indicators_for_year(BY_CODE, 2023)
    assert ind["period"] == "2023"
    assert ind["mobile_penetration"] == pytest.approx(91.8, abs=0.2)   # 10.40M/11.331M×100
    assert ind["fixed_broadband_penetration"] == 10.9                  # el de 2023, no 11.2
    # 2023 no tiene % hogares (solo 2024) → None, no se filtra desde 2024.
    assert ind["households_internet"] is None


def test_parse_for_year_missing_year_is_none():
    from shared.data.itu_client import parse_indicators_for_year
    ind = parse_indicators_for_year(BY_CODE, 2019)  # sin dato en ningún code
    assert ind["mobile_penetration"] is None and ind["fixed_broadband_penetration"] is None


# ── backfill_scores_itu: un IDT por año de cobertura plena ──────────────────────

def _hist_by_code():
    # 2019: solo móvil (cobertura parcial → NO se persiste). 2020-2024: 3 pilares.
    pop = {y: 11_000_000.0 + 90_000.0 * (y - 2019) for y in range(2019, 2025)}
    mob = {y: 9_000_000.0 + 350_000.0 * (y - 2019) for y in range(2019, 2025)}
    mbb = {y: 6_500_000.0 + 450_000.0 * (y - 2020) for y in range(2020, 2025)}  # desde 2020
    fbb = {y: 8.0 + 0.8 * (y - 2020) for y in range(2020, 2025)}                # desde 2020
    return {CODE_POPULATION: pop, CODE_MOBILE: mob,
            CODE_MOBILE_BROADBAND: mbb, CODE_FIXED_BROADBAND: fbb, CODE_HH_INTERNET: {}}


def test_backfill_persists_only_full_coverage_years(db):
    from modules.telecom_intel.service import backfill_scores_itu
    r = backfill_scores_itu(db, by_code=_hist_by_code())
    periods = sorted(s.period for s in db.query(TelecomScore).all())
    assert periods == ["2020", "2021", "2022", "2023", "2024"]   # 2019 (parcial) excluido
    assert r["period"] == "2024" and r["periods"] == periods
    for s in db.query(TelecomScore).all():
        assert s.coverage == pytest.approx(1.0, abs=1e-6)         # todos comparables


def test_backfill_is_as_of_and_idempotent(db):
    from modules.telecom_intel.service import backfill_scores_itu
    bc = _hist_by_code()
    backfill_scores_itu(db, by_code=bc)
    n1 = db.query(TelecomScore).count()
    backfill_scores_itu(db, by_code=bc)                          # re-run
    assert db.query(TelecomScore).count() == n1                 # upsert por período
    # As-of: el score 2021 usa la penetración de 2021, no la de 2024.
    s2021 = db.query(TelecomScore).filter_by(period="2021").first()
    s2024 = db.query(TelecomScore).filter_by(period="2024").first()
    assert s2021.mobile_penetration != s2024.mobile_penetration
    assert s2021.telecom_score != s2024.telecom_score


def test_backfill_prunes_legacy_quarterly_scores(db):
    # ITU es la serie canónica anual; el backfill RETIRA los trimestres INDOTEL
    # heredados (2022-Q1, congelado, otra metodología) para no dejar una serie mixta.
    from modules.telecom_intel.service import backfill_scores_itu
    db.add(TelecomScore(period="2022-Q1", telecom_score=55.0, band="Vigilancia",
                        coverage=1.0, model_version="1.0"))
    db.commit()
    r = backfill_scores_itu(db, by_code=_hist_by_code())
    assert db.query(TelecomScore).filter_by(period="2022-Q1").first() is None
    assert r["pruned_legacy"] == 1
    # Los años ITU (anuales) quedan intactos.
    periods = {s.period for s in db.query(TelecomScore).all()}
    assert periods == {"2020", "2021", "2022", "2023", "2024"}
    assert all("-Q" not in p for p in periods)
