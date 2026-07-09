"""Tests for the DGA trade-by-partner sync + the /partners source metadata.

Sync is exercised with a fixture-backed stub client (no network): it persists
partner flows into ``TradeFlow`` with the sentinel product, is idempotent per
``(period, partner, direction)``, and fails closed when the client raises. The
partner report prefers the fresh DGA quarterly cut and always declares its
source/period/frequency.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.base_client import Record
from shared.data.dga_partners_client import SERIES, DGAPartnersError
from shared.data.lineage import Lineage
from shared.database.base import Base
from modules.trade_intel.models.models import TradeDirection, TradeFlow
from modules.trade_intel.partners import partner_concentration_report
from modules.trade_intel.partners_sync import (
    PARTNER_PRODUCT,
    dga_partners_sync,
    is_partner_flow,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _rec(period, direction, partner, value):
    lineage = Lineage(source="DGA (Power BI)", license="lic", fetched_at=date.today())
    return Record(series=SERIES, period=period, value=value, lineage=lineage,
                  unit="USD", dimension=f"{direction}:{partner}")


class _StubClient:
    """Fixture-backed stub standing in for DGAPartnersClient."""

    def __init__(self, records=None, error=None):
        self._records = records or []
        self._error = error

    def fetch(self):
        if self._error:
            raise self._error
        return list(self._records)


def _sample_records():
    return [
        _rec("2026-Q1", "export", "Estados Unidos", 1000.0),
        _rec("2026-Q1", "export", "China", 200.0),
        _rec("2026-Q1", "import", "Estados Unidos", 3000.0),
        _rec("2026-Q1", "import", "China", 1500.0),
        _rec("2025-Q4", "export", "Estados Unidos", 900.0),
    ]


def test_sync_persists_partner_flows_with_sentinel(db):
    res = dga_partners_sync(db, client=_StubClient(_sample_records()))
    assert res["records"] == 5 and res["created"] == 5 and res["updated"] == 0
    assert res["latest"] == "2026-Q1"
    rows = db.query(TradeFlow).all()
    assert len(rows) == 5
    assert all(is_partner_flow(r) for r in rows)
    assert all(r.product == PARTNER_PRODUCT and r.source == "DGA (Power BI)" for r in rows)
    us_imp = db.query(TradeFlow).filter_by(
        period="2026-Q1", partner="Estados Unidos", direction=TradeDirection.import_).one()
    assert us_imp.value == 3000.0 and us_imp.unit == "USD"


def test_sync_is_idempotent_per_key(db):
    dga_partners_sync(db, client=_StubClient(_sample_records()))
    # second run with an updated value must UPDATE, not duplicate
    updated = _sample_records()
    updated[0] = _rec("2026-Q1", "export", "Estados Unidos", 1111.0)
    res = dga_partners_sync(db, client=_StubClient(updated))
    assert res["created"] == 0 and res["updated"] == 5
    assert db.query(TradeFlow).count() == 5
    us_exp = db.query(TradeFlow).filter_by(
        period="2026-Q1", partner="Estados Unidos", direction=TradeDirection.export).one()
    assert us_exp.value == 1111.0


def test_sync_does_not_touch_hs_chapter_rows(db):
    # a pre-existing HS-chapter row (different product) must survive the partner sync
    db.add(TradeFlow(product="Animales vivos", direction=TradeDirection.export,
                     value=42.0, period="2026-Q1", partner=None, source="DGA"))
    db.commit()
    dga_partners_sync(db, client=_StubClient(_sample_records()))
    chapter = db.query(TradeFlow).filter_by(product="Animales vivos").one()
    assert chapter.value == 42.0
    assert db.query(TradeFlow).filter_by(product=PARTNER_PRODUCT).count() == 5


def test_sync_fails_closed_on_client_error(db):
    res = dga_partners_sync(db, client=_StubClient(error=DGAPartnersError("boom")))
    assert res["records"] == 0 and "boom" in res["error"]
    assert db.query(TradeFlow).count() == 0   # nothing fabricated


def test_partners_report_prefers_fresh_dga_with_quarterly_metadata(db):
    dga_partners_sync(db, client=_StubClient(_sample_records()))
    rep = partner_concentration_report(db=db)
    assert rep["has_data"] is True
    assert rep["source"] == "DGA (Power BI)"
    assert rep["period"] == "2026-Q1"          # latest quarter, not 2025-Q4
    assert rep["frequency"] == "trimestral"
    assert rep["unit"] == "USD"
    # top export partner in 2026-Q1 is the US (1000 vs 200)
    assert rep["export"]["top"][0]["partner"] == "Estados Unidos"
    assert rep["export"]["n_partners"] == 2
    assert rep["import"]["n_partners"] == 2


def test_partners_report_falls_back_to_comtrade_annual_when_no_dga(db):
    # no DGA rows persisted → fall back to the annual Comtrade fixture, labelled as such
    rep = partner_concentration_report(db=db)
    assert rep["has_data"] is True
    assert rep["frequency"] == "anual"
    assert "-Q" not in rep["period"]           # an annual period, not a quarter
