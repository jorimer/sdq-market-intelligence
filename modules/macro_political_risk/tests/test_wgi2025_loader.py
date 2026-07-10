"""Tests for the WGI-2025 loader (Fase A) — ingest of the canonical governance
asset with the absolute 0-100 series, confidence intervals and source breakdown."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.macro_political_risk.models.models import (  # noqa: F401 — register tables
    CountryVariable,
)
from modules.macro_political_risk.wgi2025_loader import (
    ingest_wgi2025,
    load_asset,
)

_ASSET = {
    "meta": {"source": "WGI 2025"},
    "data": {
        "DOM": {
            "wgi_rule_of_law": {
                "2023": {"score": 52.8, "se": 2.5, "ci_lo": 48.7, "ci_hi": 56.9,
                          "n_sources": 12, "sources": {"BTI": 0.6, "EIU": 0.5}},
                "2024": {"score": 53.83, "se": 2.66, "ci_lo": 49.46, "ci_hi": 58.19,
                          "n_sources": 12, "sources": {"BTI": 0.62, "WJP": 0.51}},
            },
        },
        "CRI": {
            "wgi_rule_of_law": {
                "2024": {"score": 67.58, "se": 2.4, "ci_lo": 63.6, "ci_hi": 71.5,
                          "n_sources": 11, "sources": {"BTI": 0.9}},
            },
        },
    },
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


def _get(db, iso2, period, var):
    return (
        db.query(CountryVariable)
        .filter_by(iso_code=iso2, period=period, variable=var)
        .one()
    )


def test_ingest_maps_iso3_to_iso2_and_stores_score_and_meta(db):
    res = ingest_wgi2025(db, asset=_ASSET)
    assert res["upserts"] == 3
    assert res["economies"] == 2
    assert res["years"] == ["2023", "2024"]
    assert res["source"] == "WGI-2025"

    row = _get(db, "DO", "2024", "wgi_rule_of_law")
    assert row.value == pytest.approx(53.83)
    assert row.source == "WGI-2025"
    assert row.meta["n_sources"] == 12
    assert row.meta["ci_lo"] == pytest.approx(49.46)
    assert row.meta["ci_hi"] == pytest.approx(58.19)
    assert row.meta["sources"] == {"BTI": 0.62, "WJP": 0.51}

    # Costa Rica (iso3 CRI → iso2 CR) present too.
    assert _get(db, "CR", "2024", "wgi_rule_of_law").value == pytest.approx(67.58)


def test_ingest_is_idempotent(db):
    ingest_wgi2025(db, asset=_ASSET)
    ingest_wgi2025(db, asset=_ASSET)
    rows = db.query(CountryVariable).filter_by(
        iso_code="DO", period="2024", variable="wgi_rule_of_law"
    ).all()
    assert len(rows) == 1


def test_ingest_supersedes_legacy_wgi_row(db):
    # A legacy WGI-sync row (scalar, no meta) is replaced by WGI-2025 in place.
    legacy = CountryVariable(
        iso_code="DO", period="2024", variable="wgi_rule_of_law",
        value=99.0, source="WGI", meta=None,
    )
    db.add(legacy)
    db.commit()

    ingest_wgi2025(db, asset=_ASSET)
    row = _get(db, "DO", "2024", "wgi_rule_of_law")
    assert row.value == pytest.approx(53.83)
    assert row.source == "WGI-2025"
    assert row.meta is not None


def test_committed_asset_covers_do_full_series():
    # The real committed asset parses and carries DO's full 1996-2024 series.
    asset = load_asset()
    do = asset["data"]["DOM"]
    assert set(asset["meta"]["variables"]) == {
        "wgi_voice_accountability", "wgi_political_stability",
        "wgi_gov_effectiveness", "wgi_regulatory_quality",
        "wgi_rule_of_law", "wgi_control_corruption",
    }
    rl = do["wgi_rule_of_law"]
    assert rl["2024"]["score"] == pytest.approx(53.83, abs=0.05)
    assert rl["2024"]["n_sources"] == 12
    assert len(rl) >= 24  # WGI biennial pre-2002 → ~26 annual points


def test_governance_profile_returns_trajectory_and_meta(db):
    from modules.macro_political_risk.service import get_governance_profile

    ingest_wgi2025(db, asset=_ASSET)
    prof = get_governance_profile(db, "DO")
    assert prof["period"] == "2024"
    rl = prof["dimensions"]["wgi_rule_of_law"]
    assert rl["label"] == "Estado de derecho"
    assert rl["score"] == pytest.approx(53.83)
    assert rl["ci_lo"] == pytest.approx(49.46) and rl["ci_hi"] == pytest.approx(58.19)
    assert rl["n_sources"] == 12
    # Trajectory is chronological (oldest → newest), 2 points for DO in the fixture.
    traj = rl["trajectory"]
    assert [t["year"] for t in traj] == ["2023", "2024"]
    assert traj[-1]["score"] == pytest.approx(53.83)


def test_governance_profile_omits_dimensions_without_data(db):
    from modules.macro_political_risk.service import get_governance_profile

    ingest_wgi2025(db, asset=_ASSET)
    prof = get_governance_profile(db, "DO")
    # The fixture only carries rule_of_law → the other five are omitted, not faked.
    assert set(prof["dimensions"]) == {"wgi_rule_of_law"}


def test_governance_profile_pins_to_requested_period(db):
    from modules.macro_political_risk.service import get_governance_profile

    ingest_wgi2025(db, asset=_ASSET)
    prof = get_governance_profile(db, "DO", period="2023")
    rl = prof["dimensions"]["wgi_rule_of_law"]
    assert rl["period"] == "2023"
    assert rl["score"] == pytest.approx(52.8)
    # Trajectory always spans the full series regardless of the pinned period.
    assert len(rl["trajectory"]) == 2
