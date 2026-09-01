"""Tests for the single-source IAI assembly (T-E3-3): real BCRD + contract macro
+ declared rubric, with provenance. Offline (in-memory DB + synthetic contract)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.contracts import APP_SETTING_KEY, sector_macro_exposure
from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — register table
from shared.reference.sector_variables import SectorVariable  # noqa: F401 — register table
from modules.sector_intel.service import assemble_iai_dataset, get_sector_variables


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _seed_sector_var(db, sector, var, value, period="2024"):
    db.add(SectorVariable(sector_code=sector, dimension="sector", variable=var,
                          value=value, period=period, source="BCRD"))


def _set_contract(db, factors):
    db.add(AppSetting(key=APP_SETTING_KEY, value=json.dumps({"factors": factors}), is_secret=False))


def _set_wgi(db, series):
    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY
    db.add(AppSetting(key=WGI_REGULATORY_KEY, value=json.dumps({"series": series}), is_secret=False))


# ── sector_macro_exposure helper ──────────────────────────────────
def test_macro_exposure_nudges_by_impacting_factors():
    factors = [
        {"direction": "adverso", "magnitude": "alto", "impacted_sectors": [{"slug": "turismo"}]},
        {"direction": "favorable", "magnitude": "moderado", "impacted_sectors": [{"slug": "comercio"}]},
    ]
    assert sector_macro_exposure(factors, "turismo") == 40.0      # 50 - 10
    assert sector_macro_exposure(factors, "comercio") == 56.0     # 50 + 6
    assert sector_macro_exposure(factors, "salud") == 50.0        # untouched → neutral


# ── get_sector_variables ──────────────────────────────────────────
def test_get_sector_variables_latest_period(db):
    _seed_sector_var(db, "turismo", "sector_size", 8.0, "2023")
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    db.commit()
    out = get_sector_variables(db)
    assert out["sectors"]["turismo"]["sector_size"] == 8.9   # latest wins
    assert out["period"] == "2024" and out["has_data"]


def test_period_key_orders_mixed_formats():
    from modules.sector_intel.service import _period_key

    # annual is the connector's format; a stray quarterly must still sort right
    assert _period_key("2025") > _period_key("2024")
    assert _period_key("2025-Q1") < _period_key("2025-Q4")
    # the annual figure is canonical → beats any quarter of its year (and stale
    # quarterly cruft from the legacy fixture-POST flow)
    assert _period_key("2025") > _period_key("2025-Q4")


# ── assemble_iai_dataset ──────────────────────────────────────────
def test_assemble_merges_real_and_rubric_with_sources(db):
    _seed_sector_var(db, "turismo", "sector_size", 8.9)
    _seed_sector_var(db, "turismo", "sector_growth", 9.5)
    _set_contract(db, [
        {"direction": "adverso", "magnitude": "moderado", "impacted_sectors": [{"slug": "turismo"}]},
    ])
    db.commit()

    asm = assemble_iai_dataset(db)
    assert len(asm["dataset"]) == 17            # full economy catalog
    t = asm["dataset"]["turismo"]
    src = asm["sources"]["turismo"]
    # real (BCRD) sector dim
    assert t["sector_size"] == 8.9 and src["sector_size"] == "live"
    assert t["sector_growth"] == 9.5 and src["sector_growth"] == "live"
    # real macro_exposure from the contract (adverse moderate → 50 - 6)
    assert t["macro_exposure"] == 44.0 and src["macro_exposure"] == "live"
    # rubric dims — uniform neutral 50 (partial overrides would distort the min-max
    # ranking, so the rubric is uniform until real data covers all sectors)
    assert src["ease_of_business"] == "rubric"
    assert t["ease_of_business"] == 50
    assert asm["dataset"]["salud"]["ease_of_business"] == 50
    assert asm["dataset"]["salud"]["macro_exposure"] == 50.0   # untouched by factors
    # SGPS histórico ahora es REAL (BCRD sector_growth): turismo creció 9.5% →
    # 50 + 9.5*(50/15) = 81.67 (escala absoluta, no min-max). Estructural sin ENAE
    # queda en la rúbrica declarada (50), rotulado rúbrica.
    assert asm["sgps_inputs"]["turismo"]["historical"] == pytest.approx(81.67, abs=0.01)
    assert asm["sgps_sources"]["turismo"]["historical"] == "live"
    assert asm["sgps_inputs"]["turismo"]["structural"] == 50
    assert asm["sgps_sources"]["turismo"]["structural"] == "rubric"
    assert asm["has_live"] is True


def test_backfill_scores_all_periods_and_purges_cruft(db):
    from modules.sector_intel.models.models import SectorScore
    from modules.sector_intel.service import backfill_sector_scores, get_latest

    # real BCRD data for two years
    _seed_sector_var(db, "turismo", "sector_size", 8.0, "2023")
    _seed_sector_var(db, "turismo", "sector_growth", 5.0, "2023")
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    _seed_sector_var(db, "turismo", "sector_growth", 9.5, "2024")
    # stale cruft from the legacy fixture-POST flow (a quarterly period)
    db.add(SectorScore(sector_code="turismo", period="2024-Q4", iai_score=82.1, model_version="1.0"))
    db.commit()

    res = backfill_sector_scores(db)
    assert res["errors"] == []
    assert set(res["periods"]) == {"2023", "2024"} and res["latest"] == "2024"
    assert res["purged"] == 1 and "2024-Q4" in res["purged_periods"]
    # persisted scores are exactly the real backfill — no cruft, no fixture remnants
    assert {s.period for s in db.query(SectorScore).all()} == {"2023", "2024"}
    # getLatest returns the canonical (annual) latest
    assert get_latest(db, "turismo").period == "2024"


def test_assemble_without_contract_macro_is_neutral_rubric(db):
    _seed_sector_var(db, "comercio", "sector_size", 12.9)
    db.commit()
    asm = assemble_iai_dataset(db)
    c = asm["dataset"]["comercio"]
    assert c["macro_exposure"] == 50.0
    assert asm["sources"]["comercio"]["macro_exposure"] == "rubric"   # no contract → declared
    assert asm["sources"]["comercio"]["sector_size"] == "live"
    assert asm["sources"]["comercio"]["regulatory_quality"] == "rubric"  # no WGI → declared
    assert c["regulatory_quality"] == 50


def test_wgi_regulatory_quality_live_and_uniform_across_sectors(db):
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    _set_wgi(db, {"2023": 56.0, "2024": 58.1})
    db.commit()

    import statistics

    asm = assemble_iai_dataset(db, period="2024")
    for slug in ("turismo", "mineria", "salud"):                 # national → same for all
        assert asm["dataset"][slug]["regulatory_quality"] == 58.1
        assert asm["sources"][slug]["regulatory_quality"] == "live"
    # regulatory_volatility ahora también es real: std de la serie WGI, nacional (uniforme).
    vol = statistics.pstdev([56.0, 58.1])
    for slug in ("turismo", "mineria", "salud"):
        assert asm["dataset"][slug]["regulatory_volatility"] == pytest.approx(vol)
        assert asm["sources"][slug]["regulatory_volatility"] == "live"


def test_wgi_regulatory_latest_fallback_for_current_period(db):
    # WGI lags: the latest sector period (2025) has no WGI obs → use the latest (2024).
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2025")
    _set_wgi(db, {"2023": 56.0, "2024": 58.1})
    db.commit()
    asm = assemble_iai_dataset(db, period="2025")
    assert asm["dataset"]["turismo"]["regulatory_quality"] == 58.1   # latest-available
    assert asm["sources"]["turismo"]["regulatory_quality"] == "live"


def _seed_employment(db, branch, value, period="2024"):
    db.add(SectorVariable(sector_code=branch, dimension="labor_encft",
                          variable="employment", value=value, period=period, source="ONE"))


def _set_operating_cost(db, series, year="2025"):
    from modules.sector_intel.sectors_sync import OPERATING_COST_KEY
    db.add(AppSetting(key=OPERATING_COST_KEY,
                      value=json.dumps({"series": series, "year": year}), is_secret=False))


from shared.data.bcrd_sectors import sector_catalog

_ALL_SLUGS = [s for s, _n in sector_catalog()]
_ALL_BRANCHES = ["agricultura", "industrias", "energia", "construccion", "comercio",
                 "turismo", "transporte_comunicaciones", "financiero",
                 "administracion_publica", "otros_servicios"]


def _seed_full_coverage(db):
    """Real operating_cost (17 slugs) + employment (10 branches) → full coverage."""
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    for i, br in enumerate(_ALL_BRANCHES):
        _seed_employment(db, br, 100000.0 + i * 10000, "2024")
    _set_operating_cost(db, {slug: 30000.0 + i * 1000 for i, slug in enumerate(_ALL_SLUGS)})


def test_full_coverage_takes_operating_cost_and_labor_live(db):
    _seed_full_coverage(db)
    db.commit()
    asm = assemble_iai_dataset(db, period="2024")
    # both dims are live for ALL 17 slugs (no partial override)
    assert all(s["operating_cost"] == "live" for s in asm["sources"].values())
    assert all(s["labor_availability"] == "live" for s in asm["sources"].values())
    # bundle proxy: the 3 industrias slugs share the branch employment
    ind = asm["dataset"]["manufactura_local"]["labor_availability"]
    assert asm["dataset"]["zonas_francas"]["labor_availability"] == ind
    assert asm["dataset"]["mineria"]["labor_availability"] == ind


def test_partial_coverage_stays_full_rubric(db):
    """A partial snapshot must NOT override — it would sink rubric sectors to the
    min-max floor (the artefact the doctrine forbids). All-or-nothing."""
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    _seed_employment(db, "turismo", 333000.0, "2024")       # only 1 of 10 branches
    _set_operating_cost(db, {"turismo": 26113.0, "mineria": 79478.0})  # only 2 of 17 slugs
    db.commit()
    asm = assemble_iai_dataset(db, period="2024")
    assert all(s["operating_cost"] == "rubric" for s in asm["sources"].values())
    assert all(s["labor_availability"] == "rubric" for s in asm["sources"].values())
    assert asm["dataset"]["turismo"]["operating_cost"] == 50   # not the real 26113
    assert asm["dataset"]["turismo"]["labor_availability"] == 50


def test_wgi_regulatory_sync_persists_series(db, monkeypatch):
    import shared.data.wgi_client as wgi

    monkeypatch.setattr(wgi, "fetch_wgi_indicator",
                        lambda code, isos, mrv=12: ([{"date": "2024", "value": 58.13},
                                                     {"date": "2023", "value": 56.0}], "2026-03-18"))
    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY, wgi_regulatory_sync

    res = wgi_regulatory_sync(db)
    assert res["years"] == 2 and res["latest"] == 58.13 and res["errors"] == []
    row = db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).first()
    assert row is not None and json.loads(row.value)["series"]["2024"] == 58.13


def _set_hci(db, series):
    from modules.sector_intel.sectors_sync import HUMAN_CAPITAL_KEY
    db.add(AppSetting(key=HUMAN_CAPITAL_KEY,
                      value=json.dumps({"series": series}), is_secret=False))


def test_human_capital_sync_scales_and_persists(db, monkeypatch):
    # El HCI viene 0-1; el sync lo escala ×100 a la escala del IAI y lo persiste.
    import shared.data.wgi_client as wgi

    monkeypatch.setattr(wgi, "fetch_wgi_indicator",
                        lambda code, isos, mrv=8: ([{"date": "2020", "value": 0.5028},
                                                    {"date": "2018", "value": 0.5069}], "2020-09-01"))
    from modules.sector_intel.sectors_sync import HUMAN_CAPITAL_KEY, human_capital_sync

    res = human_capital_sync(db)
    assert res["years"] == 2 and res["latest"] == pytest.approx(50.28) and res["errors"] == []
    row = db.query(AppSetting).filter(AppSetting.key == HUMAN_CAPITAL_KEY).first()
    assert row is not None and json.loads(row.value)["series"]["2020"] == pytest.approx(50.28)


def test_skills_index_live_from_hci_uniform_ease_stays_rubric(db):
    # skills_index sube a real (HCI nacional, uniforme para los 17); ease_of_business
    # sigue rúbrica (sin fuente viva). Ambas nacional-uniformes → no cambian el ranking.
    _seed_sector_var(db, "turismo", "sector_size", 8.9, "2024")
    _set_hci(db, {"2020": 50.28})   # HCI aplicado con fallback al último disponible
    db.commit()
    asm = assemble_iai_dataset(db, period="2024")
    for slug in ("turismo", "mineria", "salud"):                 # nacional → igual para todos
        assert asm["dataset"][slug]["skills_index"] == pytest.approx(50.28)
        assert asm["sources"][slug]["skills_index"] == "live"
        # ease_of_business no tiene fuente viva → rúbrica declarada, rotulada
        assert asm["sources"][slug]["ease_of_business"] == "rubric"
        assert asm["dataset"][slug]["ease_of_business"] == 50


# ── SGPS factor sourcing (histórico all-17 · estructural ~9/17 honesto) ────────
def _seed_enae(db, enae_key, ingresos, utilidad, period="2022"):
    from shared.data.enae_activity import VAR_INGRESOS, VAR_UTILIDAD
    from modules.sector_intel.sectors_sync import ENAE_DIMENSION
    db.add(SectorVariable(sector_code=enae_key, dimension=ENAE_DIMENSION,
                          variable=VAR_INGRESOS, value=ingresos, period=period, source="ONE"))
    db.add(SectorVariable(sector_code=enae_key, dimension=ENAE_DIMENSION,
                          variable=VAR_UTILIDAD, value=utilidad, period=period, source="ONE"))


def test_sgps_historical_is_real_all17_from_growth_trailing_mean(db):
    # Track record: la media de la ventana reciente de crecimiento real → 0-100 con
    # escala ABSOLUTA fija (0%→50, ±15pp cubre la banda). Multi-período se promedia.
    _seed_sector_var(db, "turismo", "sector_growth", 5.0, "2023")
    _seed_sector_var(db, "turismo", "sector_growth", 9.5, "2024")   # media = 7.25
    _seed_sector_var(db, "salud", "sector_growth", 0.0, "2024")     # neutral → 50
    db.commit()
    asm = assemble_iai_dataset(db, period="2024")
    assert asm["sgps_inputs"]["turismo"]["historical"] == pytest.approx(74.17, abs=0.01)
    assert asm["sgps_sources"]["turismo"]["historical"] == "live"
    assert asm["sgps_inputs"]["salud"]["historical"] == 50.0
    assert asm["sgps_sources"]["salud"]["historical"] == "live"
    # un slug sin ninguna serie de crecimiento cae a la rúbrica declarada, rotulada
    assert asm["sgps_inputs"]["financiero"]["historical"] == 50
    assert asm["sgps_sources"]["financiero"]["historical"] == "rubric"


def test_sgps_structural_partial_honest_from_enae_margin(db):
    # Estructural = margen ENAE (utilidad/ingresos) en escala absoluta (0.10→50,
    # +1pp→+4pts). Cobertura PARCIAL honesta: solo los slugs del marco ENAE; el resto
    # queda en rúbrica-50 rotulada (la mezcla directa del SGPS no distorsiona).
    _seed_sector_var(db, "comercio", "sector_size", 12.0, "2022")
    _seed_enae(db, "comercio", ingresos=1000.0, utilidad=200.0)   # margen 0.20 → 90
    db.commit()
    asm = assemble_iai_dataset(db, period="2022")
    assert asm["sgps_inputs"]["comercio"]["structural"] == pytest.approx(90.0, abs=0.01)
    assert asm["sgps_sources"]["comercio"]["structural"] == "live"
    # slug fuera del marco ENAE (salud): rúbrica declarada, rotulada
    assert asm["sgps_inputs"]["salud"]["structural"] == 50
    assert asm["sgps_sources"]["salud"]["structural"] == "rubric"


def test_sgps_provenance_is_stamped_into_persisted_breakdown(db):
    # El cableado completo: backfill → compute_and_persist pasa sgps_sources →
    # compute_sgps → sgps_breakdown.factors[*].source. Antes salía siempre "rubric".
    from modules.sector_intel.models.models import SectorScore
    from modules.sector_intel.service import backfill_sector_scores

    _seed_sector_var(db, "comercio", "sector_size", 12.0, "2022")
    _seed_sector_var(db, "comercio", "sector_growth", 6.0, "2022")
    _seed_enae(db, "comercio", ingresos=1000.0, utilidad=200.0)
    db.commit()
    res = backfill_sector_scores(db)
    assert res["errors"] == []
    row = db.query(SectorScore).filter_by(sector_code="comercio", period="2022").first()
    factors = row.sgps_breakdown["factors"]
    assert factors["historical"]["source"] == "live"     # BCRD crecimiento
    assert factors["structural"]["source"] == "live"      # margen ENAE
    assert factors["acceleration"]["source"] == "live"    # eventos upstream
    # un slug sin ENAE mantiene el estructural en rúbrica rotulada
    salud = db.query(SectorScore).filter_by(sector_code="salud", period="2022").first()
    assert salud.sgps_breakdown["factors"]["structural"]["source"] == "rubric"
