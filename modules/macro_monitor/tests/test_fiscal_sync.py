"""Tests for the fiscal pulse sync (Hacienda + DGII → MacroSeries)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.dgii_client import DGIIClient
from shared.data.hacienda_client import HaciendaClient
from shared.database.base import Base
from modules.macro_monitor.models.models import MacroSeries  # noqa: F401 — register table
from modules.macro_monitor.service import fiscal_sync


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


def _fixture_clients():
    return {"fiscal_eo": HaciendaClient(mode="fixture"), "fiscal_dgii": DGIIClient(mode="fixture")}


def test_sync_persists_namespaced_fiscal_series(db):
    res = fiscal_sync(db, clients=_fixture_clients())
    assert res["errors"] == []
    assert res["touched"] > 0
    codes = {r.series_code for r in db.query(MacroSeries).all()}
    # both sources land under their own namespace, one code per fiscal line
    assert "fiscal_eo.ingresos" in codes
    assert "fiscal_eo.balance_global" in codes      # the deficit/surplus
    assert "fiscal_dgii.total" in codes
    assert all(c.startswith("fiscal_eo.") or c.startswith("fiscal_dgii.") for c in codes)
    # periods are monthly YYYY-MM; provenance stamped
    row = db.query(MacroSeries).filter_by(series_code="fiscal_eo.ingresos").first()
    assert len(row.period) == 7 and row.period[4] == "-" and row.source == "Hacienda"


def test_sync_is_idempotent(db):
    fiscal_sync(db, clients=_fixture_clients())
    n1 = db.query(MacroSeries).count()
    fiscal_sync(db, clients=_fixture_clients())
    assert db.query(MacroSeries).count() == n1     # upsert in place, no duplicates


def test_sync_best_effort_when_one_source_fails(db):
    class _Boom(DGIIClient):
        def fetch(self, series=None, period=None):
            raise RuntimeError("DGII caído")

    clients = {"fiscal_eo": HaciendaClient(mode="fixture"), "fiscal_dgii": _Boom(mode="fixture")}
    res = fiscal_sync(db, clients=clients)
    assert res["errors"] and "DGII caído" in res["errors"][0]
    codes = {r.series_code for r in db.query(MacroSeries).all()}
    assert any(c.startswith("fiscal_eo.") for c in codes)        # Hacienda still persisted
    assert not any(c.startswith("fiscal_dgii.") for c in codes)  # DGII skipped, not fabricated
