"""Tests del backfill histórico del IRMP (trayectoria). Offline: series + eventos
inyectados, sin red ni BigQuery."""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.macro_political_risk.models.models import (  # noqa: F401 — register tables
    Country,
    DimensionScore,
    IRMPSnapshot,
)
from modules.macro_political_risk.irmp_backfill import backfill_irmp_history
from modules.macro_political_risk.validation.historical import (
    IMF_INDICATORS,
    WDI_DIRECT,
    WDI_FX,
    WDI_GDP_LEVEL,
    WDI_INFLATION,
)
from shared.data.wgi_client import WGI_INDICATORS


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _full_series(year):
    """Serie sintética mínima que da dimensiones COMPLETAS a DO y CR en *year*."""
    isos = ["DO", "CR"]
    s = {}
    # macro: PIB (para CAGR Y-3..Y) + inflación + IMF deuda/fiscal
    s[WDI_GDP_LEVEL] = {i: {year - 3: 100.0, year: 112.0 if i == "DO" else 106.0} for i in isos}
    s[WDI_INFLATION] = {i: {year: 5.0} for i in isos}
    s[WDI_FX] = {i: {y: 50.0 + (y - year) for y in range(year - 6, year + 1)} for i in isos}
    for code in WDI_DIRECT:                      # current_account, fdi, reserves
        s[code] = {i: {year: -3.0} for i in isos}
    for var in WGI_INDICATORS.values():          # 6 dims WGI
        s[var] = {i: {y: 55.0 + (y - year) for y in range(year - 4, year + 1)} for i in isos}
    for var in IMF_INDICATORS.values():          # deuda + balance fiscal
        s[var] = {i: {year: -3.0} for i in isos}
    return s


def _events(year):
    return {year: {i: {"news_sentiment": -1.0, "unrest_shocks": 2.0, "sanctions_signal": 0.5}
                   for i in ("DO", "CR")}}


def test_backfill_persists_one_snapshot_per_year_all_dims_real(db):
    year = dt.date.today().year - 1   # el último año pasado que el backfill cubre
    res = backfill_irmp_history(
        db, start_year=year, series=_full_series(year), events_by_year=_events(year))
    assert res["years"][0] == year and res["persisted"] == 2   # DO + CR
    snaps = db.query(IRMPSnapshot).all()
    assert len(snaps) == 2
    for sn in snaps:
        assert str(sn.period_end) == f"{year}-12-31"
        # las 5 dimensiones puntuadas con dato real (ninguna vacía)
        dims = {d.dimension for d in sn.dimension_scores}
        assert dims == {"macro", "external", "political", "regulatory", "events"}
        assert sn.irmp_score is not None


def test_backfill_skips_year_without_series(db):
    # Datos solo para el último año pasado; los años sin serie se saltan (guard), no rompen.
    last = dt.date.today().year - 1
    res = backfill_irmp_history(
        db, start_year=last - 2, series=_full_series(last), events_by_year=_events(last))
    # solo el año con datos completos persiste (DO+CR); los 2 previos, sin serie, saltados
    assert res["persisted"] == 2
    assert {str(s.period_end) for s in db.query(IRMPSnapshot).all()} == {f"{last}-12-31"}


def test_gdelt_year_query_and_period_stamp():
    from shared.data.gdelt_bq_client import build_query_for_year, rows_to_records

    q = build_query_for_year()
    assert "@year" in q and "_PARTITIONTIME" in q
    recs = rows_to_records([{"fips": "DR", "news_sentiment": -2.0,
                             "unrest_shocks": 1.0, "sanctions_signal": 0.0}], period="2020")
    assert recs and all(r.period == "2020" for r in recs)
    assert any(r.dimension == "DO" and r.series == "news_sentiment" for r in recs)
