"""Tests del store refrescable de ratings soberanos + política de combinación (S&P manda)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — registra la tabla
from shared.contracts.sovereign_ratings import (
    ANCHOR_AGENCY, agency_score, combined_anchor, load_sovereign_ratings,
    overdue_ratings, save_sovereign_ratings)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AppSetting.__table__])
    return sessionmaker(bind=engine)()


def test_anchor_agency_is_sp():
    assert ANCHOR_AGENCY == "sp"


def test_agency_score_uses_declared_scale_and_moodys_map():
    assert agency_score("sp", "BB") == 45.0
    assert agency_score("fitch", "BB-") == 40.0
    # Moody's notation mapped to its S&P equivalent before scoring.
    assert agency_score("moodys", "Ba3") == 40.0      # Ba3 → BB-
    assert agency_score("moodys", "Baa3") == 55.0     # Baa3 → BBB-
    assert agency_score("sp", None) is None
    assert agency_score("sp", "ZZ") is None           # unknown grade → not guessed


def test_floor_used_without_db():
    panel = load_sovereign_ratings(None)
    assert set(panel) == {"DO", "CR", "PA", "GT", "JM"}
    assert panel["DO"]["sp"]["rating"] == "BB"


def test_combined_anchor_is_sp_without_store(db):
    # No store yet → yaml floor; anchor is S&P.
    anchor = combined_anchor("DO", db=db)
    assert anchor["agency"] == "S&P"
    assert anchor["rating"] == "BB"
    assert anchor["score"] == 45.0
    assert anchor["as_of"]  # last-action date present


def test_store_overrides_floor_but_sp_still_anchors(db):
    # A refreshed store where Fitch/Moody's sit a notch below S&P — the index must still
    # read S&P (política "S&P manda"), with the others as context only.
    save_sovereign_ratings(db, {
        "DO": {
            "sp": {"rating": "BB", "outlook": "Stable", "action_date": "2022-12-19"},
            "fitch": {"rating": "BB-", "outlook": "Positive", "action_date": "2025-11-07"},
            "moodys": {"rating": "Ba3", "outlook": "Positive", "action_date": "2023-08-10"},
        },
    })
    anchor = combined_anchor("DO", db=db)
    assert anchor["score"] == 45.0           # S&P BB, NOT Fitch/Moody's 40
    assert anchor["rating"] == "BB"
    names = {a["name"]: a for a in anchor["agencies"]}
    assert set(names) == {"S&P", "Fitch", "Moody's"}
    assert names["Fitch"]["score"] == 40.0   # context: a notch below
    assert names["Moody's"]["score"] == 40.0
    assert names["S&P"]["is_anchor"] is True


def test_affirm_date_flows_through_anchor(db):
    save_sovereign_ratings(db, {
        "DO": {"sp": {"rating": "BB", "action_date": "2022-12-19",
                      "affirm_date": "2025-11-28"}},
    })
    anchor = combined_anchor("DO", db=db)
    assert anchor["as_of"] == "2022-12-19"       # last action
    assert anchor["affirm_date"] == "2025-11-28"  # affirmation annotation


def test_store_missing_country_falls_back_to_floor(db):
    # Store only has DO → the other panel countries come from the floor.
    save_sovereign_ratings(db, {"DO": {"sp": {"rating": "BB+", "action_date": "2026-01-01"}}})
    panel = load_sovereign_ratings(db)
    assert panel["DO"]["sp"]["rating"] == "BB+"   # from store
    assert panel["CR"]["sp"]["rating"] == "BB"    # from floor


def test_overdue_ratings_flags_old_action(db):
    save_sovereign_ratings(db, {
        "DO": {"sp": {"rating": "BB", "action_date": "2022-12-19"}},  # ~old
        "CR": {"sp": {"rating": "BB", "action_date": "2026-05-01"}},  # fresh
    })
    stale = overdue_ratings(db, max_age_months=24, today=date(2026, 7, 1))
    isos = {s["iso"] for s in stale}
    assert "DO" in isos and "CR" not in isos
    do = next(s for s in stale if s["iso"] == "DO")
    assert do["age_months"] > 24 and do["rating"] == "BB"
