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
from modules.sector_intel.models.models import SectorVariable  # noqa: F401 — register table
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
    # SGPS inputs come from the rubric too (neutral)
    assert asm["sgps_inputs"]["turismo"]["historical"] == 50
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
