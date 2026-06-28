"""Tests for sector_intel persistence, integration and events."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.sector_intel.events import (
    SECTOR_UPDATED,
    acceleration_context,
    register_subscribers,
)
from modules.sector_intel.models.models import (  # noqa: F401 — register tables
    Sector,
    SectorScore,
    SectorVariable,
)
from shared.settings.models import AppSetting  # noqa: F401 — registra app_setting (assemble lee WGI/TSS)
from modules.sector_intel.service import (
    compute_and_persist,
    get_latest,
    seed_sectors,
)

DATASET = {
    "turismo": {"gdp_growth": 5.0, "inflation_stability": 70, "ease_of_business": 65,
                "operating_cost": 40, "labor_availability": 75, "skills_index": 60,
                "regulatory_quality": 62, "regulatory_volatility": 30,
                "sector_growth": 8.0, "sector_size": 70},
    "energia": {"gdp_growth": 4.0, "inflation_stability": 68, "ease_of_business": 55,
                "operating_cost": 60, "labor_availability": 50, "skills_index": 65,
                "regulatory_quality": 58, "regulatory_volatility": 45,
                "sector_growth": 6.0, "sector_size": 60},
}
SGPS_INPUTS = {"turismo": {"historical": 75, "structural": 80}}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_bus():
    event_bus.clear()
    acceleration_context.reset()
    yield
    event_bus.clear()
    acceleration_context.reset()


def test_seed_sectors_idempotent(db):
    from modules.sector_intel.service import ANCHOR_SECTORS

    n = len(ANCHOR_SECTORS)  # full-economy BCRD catalog (~17 leaf sectors)
    assert n == 17
    assert seed_sectors(db) == n
    assert seed_sectors(db) == 0
    assert db.query(Sector).count() == n


def test_compute_and_persist_scores_each_sector(db):
    res = compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    assert len(res["sectors"]) == 2
    assert db.query(SectorScore).count() == 2
    turismo = get_latest(db, "turismo")
    assert turismo.iai_band in {"Alto", "Medio", "Bajo"}
    assert turismo.sgps_score is not None


def test_provenance_stamped_into_breakdown(db):
    """Cuando se pasan ``sources``, cada variable del breakdown persistido lleva su
    procedencia (live|rubric) — lo que el monitor de readiness usa para G1 honesto."""
    sources = {"turismo": {"operating_cost": "live", "labor_availability": "live",
                           "sector_growth": "live", "sector_size": "live",
                           "ease_of_business": "rubric"}}
    compute_and_persist(db, "2025", DATASET, SGPS_INPUTS, sources=sources)
    bd = get_latest(db, "turismo").iai_breakdown
    biz = bd["business"]["variables"]
    assert biz["operating_cost"]["source"] == "live"
    assert biz["ease_of_business"]["source"] == "rubric"
    # Variable sin entrada en sources → "rubric" por defecto (nunca se asume real).
    assert bd["regulation"]["variables"]["regulatory_quality"]["source"] == "rubric"


def test_no_sources_leaves_no_provenance(db):
    """Sin ``sources`` (p.ej. /snapshot manual) el breakdown no estampa procedencia."""
    compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    bd = get_latest(db, "turismo").iai_breakdown
    assert "source" not in bd["sector"]["variables"]["sector_growth"]


def test_publishes_sector_updated(db):
    received = []
    event_bus.subscribe(SECTOR_UPDATED, lambda p: received.append(p))
    compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    assert len(received) == 1
    assert received[0]["period"] == "2025"
    assert len(received[0]["sectors"]) == 2


def test_acceleration_integrates_upstream_events(db):
    # Wire context to bus and emit favorable upstream signals.
    register_subscribers(event_bus, acceleration_context)
    event_bus.publish("irmp.updated", {"country_code": "DO", "irmp_score": 90.0})
    event_bus.publish("trade.updated", {"resilience_score": 90.0})

    res = compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    # acceleration > neutral 50 because irmp & trade are strong
    assert res["acceleration"]["acceleration"] > 50.0


def test_idempotent_per_sector_period(db):
    compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    compute_and_persist(db, "2025", DATASET, SGPS_INPUTS)
    assert db.query(SectorScore).count() == 2


def test_empty_dataset_raises(db):
    with pytest.raises(ValueError):
        compute_and_persist(db, "2025", {})


# ─── ENAE profitability (dim negocios, real per-sector con fallback honesto) ───

def _seed_enae(db, enae_key, year, ingresos, utilidad):
    db.add(SectorVariable(sector_code=enae_key, dimension="enae", variable="ingresos",
                          period=year, value=ingresos))
    db.add(SectorVariable(sector_code=enae_key, dimension="enae", variable="utilidad",
                          period=year, value=utilidad))


def test_enae_profitability_ratio_bundle_and_partial(db):
    from modules.sector_intel.service import _load_enae_profitability
    # direct: alojamiento→turismo (utilidad/ingresos = 20/100 = 0.20)
    _seed_enae(db, "alojamiento", "2022", 100.0, 20.0)
    # bundle: manufactura→manufactura_local + zonas_francas (comparten el ratio 0.10)
    _seed_enae(db, "manufactura", "2022", 200.0, 20.0)
    # partial: electricidad+agua→energia (suma niveles, recomputa: (5+1)/(50+10)=0.10)
    _seed_enae(db, "electricidad", "2022", 50.0, 5.0)
    _seed_enae(db, "agua", "2022", 10.0, 1.0)
    db.commit()
    prof = _load_enae_profitability(db)
    assert prof["turismo"] == pytest.approx(0.20)
    assert prof["manufactura_local"] == pytest.approx(0.10)
    assert prof["zonas_francas"] == pytest.approx(0.10)
    assert prof["energia"] == pytest.approx(0.10)  # combinado, no promediado
    # slug fuera del marco ENAE → ausente (no se inventa)
    assert "agropecuario" not in prof


def test_enae_uses_latest_year(db):
    from modules.sector_intel.service import _load_enae_profitability
    _seed_enae(db, "alojamiento", "2021", 100.0, 5.0)   # viejo
    _seed_enae(db, "alojamiento", "2022", 100.0, 25.0)  # más reciente → gana
    db.commit()
    assert _load_enae_profitability(db)["turismo"] == pytest.approx(0.25)


def test_wgi_volatility_is_series_stddev(db):
    import json
    import statistics

    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY
    from modules.sector_intel.service import _load_wgi_volatility
    from shared.settings.models import AppSetting

    serie = {"2020": 50.0, "2021": 54.0, "2022": 58.0, "2023": 56.0}
    db.add(AppSetting(key=WGI_REGULATORY_KEY, value=json.dumps({"series": serie})))
    db.commit()
    assert _load_wgi_volatility(db) == pytest.approx(statistics.pstdev(serie.values()))


def test_wgi_volatility_needs_two_years(db):
    import json

    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY
    from modules.sector_intel.service import _load_wgi_volatility
    from shared.settings.models import AppSetting

    db.add(AppSetting(key=WGI_REGULATORY_KEY, value=json.dumps({"series": {"2023": 58.0}})))
    db.commit()
    assert _load_wgi_volatility(db) is None  # sin varianza computable


def test_wgi_volatility_wired_all_17(db):
    """regulatory_volatility (nacional) se aplica a TODOS los slugs como dato real."""
    import json

    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY
    from modules.sector_intel.service import assemble_iai_dataset
    from shared.settings.models import AppSetting

    seed_sectors(db)
    compute_and_persist(db, "2022", DATASET, SGPS_INPUTS)
    db.add(AppSetting(key=WGI_REGULATORY_KEY,
                      value=json.dumps({"series": {"2021": 50.0, "2022": 56.0, "2023": 58.0}})))
    db.commit()
    asm = assemble_iai_dataset(db, period="2022")
    for slug in ("turismo", "agropecuario", "construccion"):
        assert asm["sources"][slug]["regulatory_volatility"] == "live"
        assert asm["dataset"][slug]["regulatory_volatility"] > 0


def test_enae_wired_into_assemble_with_provenance(db):
    """assemble_iai_dataset marca profitability live solo donde ENAE cubre; ausente
    (no rúbrica-50) en los no cubiertos → el motor la omite, sin distorsión."""
    from modules.sector_intel.service import assemble_iai_dataset
    seed_sectors(db)
    compute_and_persist(db, "2022", DATASET, SGPS_INPUTS)  # da un período al grid
    _seed_enae(db, "alojamiento", "2022", 100.0, 18.0)
    db.commit()
    asm = assemble_iai_dataset(db, period="2022")
    # turismo (cubierto): profitability presente y marcada live
    assert asm["dataset"]["turismo"].get("profitability") == pytest.approx(0.18)
    assert asm["sources"]["turismo"]["profitability"] == "live"
    # agropecuario (no cubierto): profitability AUSENTE (ni valor ni rúbrica)
    assert "profitability" not in asm["dataset"]["agropecuario"]
    assert "profitability" not in asm["sources"]["agropecuario"]
