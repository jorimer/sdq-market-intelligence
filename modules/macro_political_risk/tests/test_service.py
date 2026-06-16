"""Tests for IRMP persistence + event publication (Fase 1B)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.events.event_bus import event_bus
from modules.macro_political_risk.events import IRMP_UPDATED
from modules.macro_political_risk.models.models import (  # noqa: F401 — register tables
    Country,
    CountryVariable,
    DimensionScore,
    IRMPSnapshot,
    RiskBand,
)
from modules.macro_political_risk.service import (
    assemble_irmp_dataset,
    compute_and_persist,
    get_country_variables,
    get_history,
    get_latest,
)

DATASET = {
    "DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0,
           "fx_volatility": 3.0, "news_sentiment": 20.0, "discretion": 30.0},
    "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0,
           "fx_volatility": 5.0, "news_sentiment": 10.0, "discretion": 40.0},
    "PA": {"gdp_cagr_3y": 1.0, "public_debt_gdp": 52.0, "wgi_rule_of_law": 50.0,
           "fx_volatility": 8.0, "news_sentiment": -10.0, "discretion": 60.0},
}


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
    yield
    event_bus.clear()


def test_persists_snapshot_and_dimensions(db):
    res = compute_and_persist(db, "DO", DATASET, date(2025, 12, 31),
                              country_name="República Dominicana", region="Caribe")
    assert "snapshot_id" in res
    snap = db.query(IRMPSnapshot).one()
    assert snap.irmp_score == res["irmp_score"]
    assert isinstance(snap.risk_band, RiskBand)
    # 5 dimension rows persisted
    assert db.query(DimensionScore).count() == 5
    # country upserted with real name
    country = db.query(Country).filter_by(iso_code="DO").one()
    assert country.name == "República Dominicana"


def test_publishes_irmp_updated(db):
    received = []
    event_bus.subscribe(IRMP_UPDATED, lambda p: received.append(p))

    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))

    assert len(received) == 1
    assert received[0]["country_code"] == "DO"
    assert received[0]["risk_band"] in {"Bajo", "Moderado", "Elevado", "Alto"}
    assert "snapshot_id" in received[0]


def test_rerun_is_idempotent_per_period(db):
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))
    # Same country + period → one snapshot, 5 dimension rows (not 10)
    assert db.query(IRMPSnapshot).count() == 1
    assert db.query(DimensionScore).count() == 5


def test_latest_and_history(db):
    compute_and_persist(db, "DO", DATASET, date(2024, 12, 31))
    compute_and_persist(db, "DO", DATASET, date(2025, 12, 31))

    latest = get_latest(db, "DO")
    assert str(latest.period_end) == "2025-12-31"

    history = get_history(db, "DO")
    assert len(history) == 2
    assert str(history[0].period_end) == "2025-12-31"  # most recent first


def test_unknown_country_raises_and_persists_nothing(db):
    with pytest.raises(KeyError):
        compute_and_persist(db, "XX", DATASET, date(2025, 12, 31))
    assert db.query(IRMPSnapshot).count() == 0


def _add_var(db, iso, period, variable, value):
    db.add(CountryVariable(iso_code=iso, period=period, variable=variable,
                           value=value, source="WGI"))


def test_country_variables_empty_table(db):
    res = get_country_variables(db)
    assert res["has_data"] is False
    assert res["period"] is None
    assert res["countries"] == {}


def test_country_variables_groups_by_country_latest_period(db):
    # Two periods present → helper defaults to the most recent ("2024").
    _add_var(db, "DO", "2023", "wgi_rule_of_law", 50.0)
    _add_var(db, "DO", "2024", "wgi_rule_of_law", 53.8)
    _add_var(db, "DO", "2024", "wgi_gov_effectiveness", 49.1)
    _add_var(db, "CR", "2024", "wgi_rule_of_law", 66.0)
    db.commit()

    res = get_country_variables(db)
    assert res["period"] == "2024"
    assert res["has_data"] is True
    assert res["countries"]["DO"] == {"wgi_rule_of_law": 53.8, "wgi_gov_effectiveness": 49.1}
    assert res["countries"]["CR"] == {"wgi_rule_of_law": 66.0}
    assert res["variables"] == ["wgi_gov_effectiveness", "wgi_rule_of_law"]


def test_country_variables_explicit_period_filter(db):
    _add_var(db, "DO", "2023", "wgi_rule_of_law", 50.0)
    _add_var(db, "DO", "2024", "wgi_rule_of_law", 53.8)
    db.commit()

    res = get_country_variables(db, period="2023")
    assert res["period"] == "2023"
    assert res["countries"]["DO"] == {"wgi_rule_of_law": 50.0}


def test_country_variables_all_sources_when_source_none(db):
    # Mixed upstreams at the same period; source=None returns them all.
    db.add(CountryVariable(iso_code="DO", period="2024", variable="wgi_rule_of_law",
                           value=53.8, source="WGI"))
    db.add(CountryVariable(iso_code="DO", period="2024", variable="public_debt_gdp",
                           value=58.8, source="IMF_WEO"))
    db.add(CountryVariable(iso_code="DO", period="2024", variable="sovereign_rating_score",
                           value=45.0, source="SDQ_DECLARED"))
    db.commit()

    res = get_country_variables(db, source=None)
    assert res["source"] == "ALL"
    assert res["countries"]["DO"] == {
        "wgi_rule_of_law": 53.8, "public_debt_gdp": 58.8, "sovereign_rating_score": 45.0,
    }
    # Filtering by a single source still narrows it.
    only_wgi = get_country_variables(db, source="WGI")
    assert only_wgi["countries"]["DO"] == {"wgi_rule_of_law": 53.8}


def test_country_variables_cross_source_lag_keeps_both(db):
    # WGI trails a year behind WDI/IMF — neither must be dropped (per-variable latest).
    db.add(CountryVariable(iso_code="DO", period="2023", variable="wgi_rule_of_law",
                           value=50.0, source="WGI"))
    db.add(CountryVariable(iso_code="DO", period="2024", variable="public_debt_gdp",
                           value=58.8, source="IMF_WEO"))
    db.commit()

    res = get_country_variables(db, source=None)
    # Both survive even though they sit at different periods.
    assert res["countries"]["DO"] == {"wgi_rule_of_law": 50.0, "public_debt_gdp": 58.8}
    assert res["period"] == "2024"   # representative = most recent observed


def test_assemble_overlays_live_over_rubric(db):
    # Rubric comes from doctrine; persisted live data overrides it where present.
    db.add(CountryVariable(iso_code="DO", period="2024", variable="public_debt_gdp",
                           value=58.8, source="IMF_WEO"))
    # A live value that also exists as a rubric var must win:
    db.add(CountryVariable(iso_code="DO", period="2024", variable="contract_enforcement",
                           value=99.0, source="WGI"))
    db.commit()

    asm = assemble_irmp_dataset(db)
    do = asm["dataset"]["DO"]
    # rubric var present (declared, from doctrine)
    assert "electoral_uncertainty" in do
    assert asm["sources"]["DO"]["electoral_uncertainty"] == "rubric"
    # live var added
    assert do["public_debt_gdp"] == 58.8
    assert asm["sources"]["DO"]["public_debt_gdp"] == "live"
    # live overrides the rubric value for the same var
    assert do["contract_enforcement"] == 99.0
    assert asm["sources"]["DO"]["contract_enforcement"] == "live"
    assert asm["has_live"] is True


def test_gdelt_sync_skips_none_and_stamps_at_vintage(db, monkeypatch):
    # Existing real data fixes the vintage; GDELT must align to it and skip gaps.
    db.add(CountryVariable(iso_code="DO", period="2024", variable="wgi_rule_of_law",
                           value=53.8, source="WGI"))
    db.commit()

    import shared.data.gdelt_client as gc
    from shared.data.base_client import Record
    from shared.data.lineage import Lineage
    from modules.macro_political_risk.gdelt_sync import gdelt_sync

    lin = Lineage(source="GDELT", license="x", fetched_at=date(2026, 6, 16))
    fake = [
        Record(series="news_sentiment", period="2026", value=2.5, lineage=lin, dimension="DO"),
        Record(series="unrest_shocks", period="2026", value=None, lineage=lin, dimension="DO"),
    ]

    class _FakeClient:
        def __init__(self, mode=None):
            pass
        def fetch(self):
            return fake

    monkeypatch.setattr(gc, "GDELTClient", _FakeClient)
    res = gdelt_sync(db)

    assert res["synced"] == 1 and res["skipped_missing"] == 1
    assert res["period"] == "2024"   # stamped at the existing data vintage, not "2026"
    # non-null tone persisted at the vintage
    rows = db.query(CountryVariable).filter_by(variable="news_sentiment").all()
    assert len(rows) == 1 and rows[0].period == "2024" and rows[0].value == 2.5
    assert rows[0].source == "GDELT"
    # the None unrest_shocks was NEVER persisted (rubric stays the fallback)
    assert db.query(CountryVariable).filter_by(variable="unrest_shocks").count() == 0


def test_assemble_rubric_only_when_no_live(db):
    asm = assemble_irmp_dataset(db)
    assert asm["has_live"] is False
    # Still returns the declared rubric for the peer set (no fabrication, no crash).
    assert set(asm["dataset"]) == {"DO", "CR", "PA", "GT", "JM"}
    assert all(v == "rubric" for v in asm["sources"]["DO"].values())


def test_country_variables_skips_null_values(db):
    # Missing value persisted as None must never surface (no fabrication).
    _add_var(db, "DO", "2024", "wgi_rule_of_law", 53.8)
    _add_var(db, "DO", "2024", "wgi_control_corruption", None)
    db.commit()

    res = get_country_variables(db)
    assert res["countries"]["DO"] == {"wgi_rule_of_law": 53.8}
    assert "wgi_control_corruption" not in res["countries"]["DO"]
