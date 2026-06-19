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
    # WDI health + ONE labour/coverage hit the network — stub them (live sensors cover).
    monkeypatch.setattr("modules.social_dev.social_sync._sync_wdi_health", lambda db, set_phase: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_one_labor", lambda db, set_phase: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_one_coverage", lambda db, set_phase: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_one_schooling", lambda db, set_phase: 0)
    monkeypatch.setattr("modules.social_dev.social_sync._sync_wb_findex", lambda db, set_phase: 0)

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
    # No national labour yet → income/informality fall back to declared rubric 50.
    assert src["income_per_capita"] == "rubric" and enr["income_per_capita"] == 50
    assert src["informality_rate"] == "rubric" and enr["informality_rate"] == 50


def test_national_labor_goes_live_for_every_region(db):
    """ONE national informality + income (proxy) apply to every region, live."""
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "informality_rate", "2024", 55.46)
    _ind(db, "nacional", "income_per_capita", "2024", 167.46)
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    for slug in ("enriquillo", "valdesia"):                  # uniform across regions
        row, src = asm["dataset"][slug], asm["sources"][slug]
        assert row["informality_rate"] == 55.46 and src["informality_rate"] == "live"
        assert row["income_per_capita"] == 167.46 and src["income_per_capita"] == "live"
    # financial_inclusion has no source → stays declared rubric.
    assert asm["sources"]["enriquillo"]["financial_inclusion"] == "rubric"


def test_parse_one_indicator_xlsx_reads_total_by_year():
    import io
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = " Ficha "                              # metadata sheet (ignored)
    wb.active["A1"] = "Ficha técnica"
    ws = wb.create_sheet("Indicador")
    ws.append(["REPÚBLICA DOMINICANA: Tasa de Informalidad…"])  # title row
    ws.append(["Año", "Total", "Hombres", "Mujeres"])           # header
    ws.append([2022, 57.56, 61.21, 52.3])
    ws.append([2023, 56.54, 60.3, 51.27])
    ws.append(["Fuente: ENCFT (BCRD)"])                         # trailing note (ignored)
    buf = io.BytesIO()
    wb.save(buf)

    from shared.data.one_client import parse_one_indicator_xlsx
    assert parse_one_indicator_xlsx(buf.getvalue()) == [(2022, 57.56), (2023, 56.54)]


def test_parse_one_indicator_tolerates_sheet_whitespace():
    """ONE sheet names often carry trailing spaces — must still be found."""
    import io
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = " Ficha "
    ws = wb.create_sheet("Indicador ")              # trailing space
    ws.append(["Año", "Total"])
    ws.append([2024, 167.46])
    wb.create_sheet("Notas")                         # later sheet must NOT win
    buf = io.BytesIO()
    wb.save(buf)

    from shared.data.one_client import parse_one_indicator_xlsx
    assert parse_one_indicator_xlsx(buf.getvalue()) == [(2024, 167.46)]


def test_discover_labor_links_prefers_latest_revision():
    from shared.data.one_client import discover_labor_links

    html = (
        '<a href="/media/aaa/tasa-de-informalidad-en-el-empleo-por-sexo-2004-2023.xlsx">old</a>'
        '<a href="/media/bbb/tasa-de-informalidad-en-el-empleo-por-sexo-2004-2024.xlsx">new</a>'
    )
    assert discover_labor_links(html)["informality_rate"].endswith("2004-2024.xlsx")


def test_parse_one_coverage_xlsx_secondary_by_region():
    """Net secondary-coverage parser: 3rd column per year-group, dev regions only."""
    import io
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Cuadro: tasa neta de cobertura, según región y provincia"])
    ws.append([None, "2023-2024", None, None, "2022-2023", None, None])  # year-group labels
    ws.append([None, "Inicial", "Primario", "Secundario", "Inicial", "Primario", "Secundario"])
    ws.append(["Total país", 30, 90, 70, 29, 89, 69])                    # skipped (not "Región …")
    ws.append(["Región Metropolitana", 33, 86, 67, 32, 85, 66])         # → ozama
    ws.append(["Distrito Nacional", 37, 87, 73, 36, 88, 72])            # province → skipped
    ws.append(["Región Cibao Norte", 34, 94, 71, 33, 93, 70])          # → cibao_norte
    buf = io.BytesIO()
    wb.save(buf)

    from shared.data.one_client import parse_one_coverage_xlsx
    rows = parse_one_coverage_xlsx(buf.getvalue())
    by = {(s, y): v for s, y, v in rows}
    assert by[("ozama", 2024)] == 67 and by[("ozama", 2023)] == 66       # Metropolitana → ozama
    assert by[("cibao_norte", 2024)] == 71                               # 3rd col = secondary
    assert all(s in {"ozama", "cibao_norte"} for s, _, _ in rows)        # país/provincia excluded


def test_coverage_goes_live_by_region_and_period(db):
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "enriquillo", "secondary_coverage", "2024", 66.8)   # valdesia has none
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    enr = asm["dataset"]["enriquillo"]
    assert enr["secondary_coverage"] == 66.8                            # by region + period
    assert asm["sources"]["enriquillo"]["secondary_coverage"] == "live"
    # A region without coverage that period → rubric, value excluded (engine skips it).
    assert asm["sources"]["valdesia"]["secondary_coverage"] == "rubric"
    assert "secondary_coverage" not in asm["dataset"]["valdesia"]


def test_indicator_units_fit_postgres_varchar40():
    """sd_indicators.unit is VARCHAR(40): SQLite ignores it, Postgres truncates →
    every declared unit string must fit (dev↔prod parity guard)."""
    from modules.social_dev.social_sync import COVERAGE_UNIT, FINDEX_UNIT, _LABOR_UNITS

    units = list(_LABOR_UNITS.values()) + [COVERAGE_UNIT, FINDEX_UNIT]
    too_long = [u for u in units if len(u) > 40]
    assert not too_long, f"unit > 40 chars (rompe en Postgres): {too_long}"


def test_findex_financial_inclusion_goes_live_latest_available(db):
    """WB Findex financial access is national + lags; the latest value goes live for
    the current IDM period (so inclusión is real even if the target year has no obs)."""
    _ind(db, "enriquillo", "poverty_rate", "2024", 31.0)
    _ind(db, "valdesia", "poverty_rate", "2024", 11.0)
    _ind(db, "nacional", "financial_inclusion", "2023", 40.06, source="WB")  # 2023, not 2024
    db.commit()

    from modules.social_dev.service import assemble_idm_dataset
    asm = assemble_idm_dataset(db)
    assert asm["period"] == "2024"
    for slug in ("enriquillo", "valdesia"):                     # national → every region, live
        assert asm["dataset"][slug]["financial_inclusion"] == 40.06
        assert asm["sources"][slug]["financial_inclusion"] == "live"


def test_sync_wb_findex_upserts_national(db, monkeypatch):
    import shared.data.wdi_client as wdi  # not re-exported by the package → real module

    monkeypatch.setattr(
        wdi, "fetch_wb_indicator",
        lambda code, isos, mrv=25: ([{"date": "2023", "value": 40.06},
                                     {"date": "2022", "value": 38.5}], None),
    )
    from modules.social_dev.social_sync import _sync_wb_findex

    n = _sync_wb_findex(db, lambda _m: None)
    db.commit()
    assert n == 2
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="nacional", theme="financial_inclusion", period="2023")
        .first()
    )
    assert row is not None and row.value == 40.06 and row.source == "WB"


def test_sync_one_schooling_upserts_national(db, monkeypatch):
    import sys

    oc_mod = sys.modules["shared.data.one_client"]  # patch the real module (re-export shadow)
    monkeypatch.setattr(oc_mod, "fetch_one_education_schooling",
                        lambda: [(2023, 9.61), (2024, 9.61)])
    from modules.social_dev.social_sync import _sync_one_schooling

    n = _sync_one_schooling(db, lambda _m: None)
    db.commit()
    assert n == 2
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="nacional", theme="schooling_years", period="2024")
        .first()
    )
    assert row is not None and row.value == 9.61 and row.source == "ONE" and row.unit == "años"


def test_sync_one_coverage_upserts_by_region(db, monkeypatch):
    import sys

    oc_mod = sys.modules["shared.data.one_client"]
    monkeypatch.setattr(
        oc_mod, "fetch_one_education_coverage",
        lambda: [("enriquillo", 2024, 66.8), ("ozama", 2024, 67.7)],
    )
    from modules.social_dev.social_sync import _sync_one_coverage

    n = _sync_one_coverage(db, lambda _m: None)
    db.commit()
    assert n == 2
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="enriquillo", theme="secondary_coverage", period="2024")
        .first()
    )
    assert row is not None and row.value == 66.8 and row.source == "ONE" and row.disaggregation == "region"


def test_discover_labor_links_matches_by_slug():
    from shared.data.one_client import discover_labor_links

    html = (
        '<a href="/media/3fxoh4pp/tasa-de-informalidad-en-el-empleo-por-sexo-2004-2024.xlsx">x</a>'
        '<a href="/media/dtmlxqpw/ingreso-laboral-promedio-por-hora-trabajada-en-ocupaci&#243;n-principal-2000-2024.xlsx">y</a>'
        '<a href="/media/zzzz/poblaci&#243;n-desocupada-2008-2024.xlsx">z</a>'  # distractor
    )
    links = discover_labor_links(html)
    assert links["informality_rate"].endswith("tasa-de-informalidad-en-el-empleo-por-sexo-2004-2024.xlsx")
    assert "ingreso-laboral-promedio-por-hora-trabajada" in links["income_per_capita"]
    assert set(links) == {"informality_rate", "income_per_capita"}            # distractor excluded


def test_sync_one_labor_upserts_national(db, monkeypatch):
    import sys  # the package re-exports `one_client`, shadowing the submodule attr →
    oc_mod = sys.modules["shared.data.one_client"]  # patch the real module object

    monkeypatch.setattr(
        oc_mod, "fetch_one_labor",
        lambda: [("informality_rate", 2024, 55.46), ("income_per_capita", 2024, 167.46)],
    )
    from modules.social_dev.social_sync import _sync_one_labor

    n = _sync_one_labor(db, lambda _m: None)
    db.commit()
    assert n == 2
    row = (
        db.query(SocialIndicator)
        .filter_by(entity_key="nacional", theme="informality_rate", period="2024")
        .first()
    )
    assert row is not None and row.value == 55.46 and row.source == "ONE"


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
