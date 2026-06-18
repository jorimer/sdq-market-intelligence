"""Tests for the ONE social connector + sync (Eje 6 Gate A). Offline."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.one_client import ONEClient, _parse_poverty_csv, region_catalog
from shared.database.base import Base
from modules.social_dev.models.models import SocialIndicator  # noqa: F401 — register table
from modules.social_dev.social_sync import one_social_sync


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


def test_parse_poverty_csv_maps_themes_and_regions():
    csv = (
        "Tasa de Pobreza ,Tipo de Regiones,Porcentaje,Año\n"
        "Pobreza General,Enriquillo,31,2024\n"
        "Pobreza Extrema, Cibao Norte ,2,2024\n"          # leading/trailing spaces
        "Pobreza General,Región Inexistente,99,2024\n"     # unknown region → skipped
    ).encode("utf-8")
    out = _parse_poverty_csv(csv)
    assert ("poverty_rate", "enriquillo", "2024", 31.0) in out
    assert ("poverty_extreme", "cibao_norte", "2024", 2.0) in out          # space-tolerant
    assert not any(slug not in dict(region_catalog()) for _, slug, _, _ in out)  # no unknowns


def test_ozama_alias_matches():
    # Ozama (Gran Santo Domingo) under a single-token rename must still map.
    for label in ("Ozama", "Metropolitana", "Gran Santo Domingo"):
        csv = f"a,b,c,d\nPobreza General,{label},20,2024\n".encode("utf-8")
        out = _parse_poverty_csv(csv)
        assert out and out[0][1] == "ozama"


def test_fixture_client_offline():
    recs = ONEClient(mode="fixture").fetch()
    assert recs, "fixture vacío — ¿se generó one.json?"
    assert {r.dimension for r in recs} == {slug for slug, _ in region_catalog()}  # 10 regions
    assert {r.series for r in recs} >= {"poverty_rate"}


def test_sync_persists_and_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(ONEClient, "_fetch_live", ONEClient._fetch_fixture)
    # WDI health hits the network — stub it out (covered by the live sensor instead).
    monkeypatch.setattr("modules.social_dev.social_sync._sync_wdi_health", lambda db, set_phase: 0)

    first = one_social_sync(db)
    assert first["errors"] == []
    assert first["synced"] > 0
    assert first["regions"] == 10
    assert "poverty_rate" in first["themes"]
    n1 = db.query(SocialIndicator).count()
    assert n1 == first["synced"]

    second = one_social_sync(db)          # upsert in place — no duplicates
    assert db.query(SocialIndicator).count() == n1

    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="enriquillo", theme="poverty_rate", period="2024")
        .first()
    )
    assert row is not None and row.source == "ONE" and row.disaggregation == "region"


def _ind(db, entity, theme, period, value, source="ONE"):
    db.add(SocialIndicator(entity_key=entity, theme=theme, period=period, value=value, source=source))


def test_assemble_idm_real_plus_rubric_with_sources(db):
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "life_expectancy", "2024", 73.9, source="WDI")
    _ind(db, "nacional", "child_mortality", "2024", 27.7, source="WDI")
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert asm["period"] == "2024" and asm["has_live"]
    assert len(asm["dataset"]) == 10                         # the 10 development regions
    enr, src = asm["dataset"]["enriquillo"], asm["sources"]["enriquillo"]
    assert enr["poverty_rate"] == 31.0 and src["poverty_rate"] == "live"   # ONE, by region
    assert enr["life_expectancy"] == 73.9 and src["life_expectancy"] == "live"  # WDI national
    assert src["income_per_capita"] == "rubric" and enr["income_per_capita"] == 50  # declared


def test_backfill_idm_scores_and_purges_cruft(db):
    from modules.social_dev.models.models import DevelopmentScore
    from modules.social_dev.service import backfill_idm_scores, get_latest

    for region, pov in (("enriquillo", 31.0), ("valdesia", 11.0)):
        _ind(db, region, "poverty_rate", "2023", pov + 1)
        _ind(db, region, "poverty_rate", "2024", pov)
    db.add(DevelopmentScore(entity_key="nacional", period="2025", development_score=60.0))  # cruft
    db.commit()

    res = backfill_idm_scores(db)
    assert res["errors"] == [] and set(res["periods"]) == {"2023", "2024"} and res["latest"] == "2024"
    assert res["purged"] == 1 and "2025" in res["purged_periods"]
    assert {s.period for s in db.query(DevelopmentScore).all()} == {"2023", "2024"}
    assert get_latest(db, "enriquillo").period == "2024"
