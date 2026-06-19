"""Tests for the AI-native by-region education extraction (T-ONE-social-f2).

Offline: the AI call itself is not exercised — we test the pure validation
(``validate_education``) and the completeness gate in ``assemble_idm_dataset``
that decides whether education goes live (real) or stays uniform rubric.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.one_client import region_catalog
from shared.database.base import Base
from modules.social_dev.education_extract import validate_education
from modules.social_dev.models.models import SocialIndicator
from modules.social_dev.service import EDUCATION_VARS, assemble_idm_dataset

VALID_SLUGS = {slug for slug, _ in region_catalog()}


# ── validate_education (pure) ─────────────────────────────────────────

def test_keeps_in_range_values():
    out = validate_education(
        {"enriquillo": {"literacy_rate": 88.5}}, VALID_SLUGS)
    assert out == {"enriquillo": {"literacy_rate": 88.5}}


def test_drops_out_of_range_as_misread():
    # literacy 30 (<50) is implausible → region dropped; 92 is in range → kept.
    # schooling_years is ignored entirely (no longer extracted by region).
    out = validate_education(
        {"enriquillo": {"literacy_rate": 30.0},
         "valdesia": {"literacy_rate": 92.0}}, VALID_SLUGS)
    assert "enriquillo" not in out
    assert out["valdesia"] == {"literacy_rate": 92.0}


def test_drops_region_with_all_none():
    # literacy out of range → no real data → region omitted entirely.
    out = validate_education(
        {"enriquillo": {"literacy_rate": 10.0}}, VALID_SLUGS)
    assert out == {}


def test_ignores_extraneous_schooling_years():
    # schooling_years is national now; even if the model returns it, it is dropped.
    out = validate_education(
        {"valdesia": {"literacy_rate": 91.3, "schooling_years": 9.0}}, VALID_SLUGS)
    assert out == {"valdesia": {"literacy_rate": 91.3}}


def test_skips_unknown_region():
    out = validate_education(
        {"region_inexistente": {"literacy_rate": 90.0}}, VALID_SLUGS)
    assert out == {}


def test_coerces_string_numbers_and_null():
    out = validate_education(
        {"valdesia": {"literacy_rate": "91.3"}, "enriquillo": {"literacy_rate": None}}, VALID_SLUGS)
    assert out == {"valdesia": {"literacy_rate": 91.3}}


def test_tolerates_garbage_shapes():
    # Non-dict value, missing keys, and None payload must not raise.
    assert validate_education({"enriquillo": "no-soy-dict"}, VALID_SLUGS) == {}
    assert validate_education(None, VALID_SLUGS) == {}
    assert validate_education({}, VALID_SLUGS) == {}


# ── assemble_idm_dataset completeness gate ────────────────────────────

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


def _ind(db, entity, theme, period, value, source="ONE"):
    db.add(SocialIndicator(entity_key=entity, theme=theme, period=period, value=value, source=source))


def _seed_poverty(db, period="2024"):
    for slug in VALID_SLUGS:
        _ind(db, slug, "poverty_rate", period, 20.0)


def test_literacy_goes_live_only_when_all_regions_present(db):
    _seed_poverty(db)
    # literacy_rate is by region (ENHOGAR), live ONLY IF every region has it (no
    # partial min-max). schooling_years is now NATIONAL — a regional value is ignored.
    for slug in VALID_SLUGS:
        if slug != "enriquillo":  # one region missing → literacy stays rubric
            _ind(db, slug, "literacy_rate", "2022", 85.0)
    db.commit()

    src = assemble_idm_dataset(db)["sources"]["valdesia"]
    assert src["literacy_rate"] == "rubric"          # incomplete → uniform rubric
    assert src["schooling_years"] == "rubric"        # no national value → rubric


def test_education_complete_promotes_both_vars(db):
    # literacy by region (all 10) + schooling national → both live for every region.
    for slug in VALID_SLUGS:
        _ind(db, slug, "poverty_rate", "2024", 20.0)
        _ind(db, slug, "literacy_rate", "2022", 85.0)
    _ind(db, "nacional", "schooling_years", "2024", 9.6)   # ONE national series
    db.commit()

    src = assemble_idm_dataset(db)["sources"]
    assert all(s["literacy_rate"] == "live" for s in src.values())    # regional, complete
    assert all(s["schooling_years"] == "live" for s in src.values())  # national → every region


def test_education_default_rubric_when_absent(db):
    _seed_poverty(db)
    db.commit()
    asm = assemble_idm_dataset(db)
    for var in EDUCATION_VARS:
        assert all(s[var] == "rubric" for s in asm["sources"].values())
        assert all(d[var] == 50 for d in asm["dataset"].values())
