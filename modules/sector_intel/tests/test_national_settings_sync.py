"""Tests for the national AppSetting syncs (WGI regulatory + WB Human Capital).

Offline: the WB fetcher (``fetch_wgi_indicator``) is monkeypatched. The WGI test is fed
rows sourced from the committed ``shared/data/fixtures/wgi.json`` (real data, via the
fixture-mode WGIClient); the HCI test uses a minimal synthetic 0-1 payload ONLY to
exercise the ×100 scaling/persistence transform (no committed fixture carries
``HD.HCI.OVRL``). Complements the happy paths in ``test_assemble_iai.py`` with the
fixture-sourced series, upsert idempotency, None filtering and the best-effort error
path. No network.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.wgi_client import WGIClient
from shared.settings.models import AppSetting
from modules.sector_intel.sectors_sync import (
    HUMAN_CAPITAL_KEY,
    WGI_REGULATORY_KEY,
    WGI_RQ_CODE,
    human_capital_sync,
    wgi_regulatory_sync,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[AppSetting.__table__])
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _wgi_fixture_rows():
    """DOM regulatory-quality rows from the committed wgi.json, shaped like the WB API."""
    recs = WGIClient(mode="fixture").fetch(series="wgi_regulatory_quality")
    return [{"date": r.period, "value": r.value, "countryiso3code": "DOM"}
            for r in recs if r.dimension == "DO"]


# ── wgi_regulatory_sync ───────────────────────────────────────────
def test_wgi_sync_persists_committed_fixture_series(db, monkeypatch):
    import shared.data.wgi_client as wgi
    rows = _wgi_fixture_rows()
    assert rows, "el fixture wgi.json debe traer wgi_regulatory_quality para DO"

    def fake(code, isos, mrv=12):
        assert code == WGI_RQ_CODE and isos == ["DOM"]
        return rows, "2026-01-01"

    monkeypatch.setattr(wgi, "fetch_wgi_indicator", fake)
    res = wgi_regulatory_sync(db)
    assert res["errors"] == [] and res["years"] == len(rows)
    setting = db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).one()
    payload = json.loads(setting.value)
    assert payload["source"] == "WGI" and payload["unit"] == "percentil 0-100"
    # The persisted series mirrors the committed fixture, year by year.
    assert payload["series"] == {r["date"]: r["value"] for r in rows}


def test_wgi_sync_upserts_in_place(db, monkeypatch):
    import shared.data.wgi_client as wgi
    monkeypatch.setattr(wgi, "fetch_wgi_indicator", lambda c, i, mrv=12: (_wgi_fixture_rows(), None))
    wgi_regulatory_sync(db)
    wgi_regulatory_sync(db)
    # One row, updated in place — never duplicated.
    assert db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).count() == 1


def test_wgi_sync_skips_null_values(db, monkeypatch):
    import shared.data.wgi_client as wgi
    rows = _wgi_fixture_rows() + [{"date": "1999", "value": None, "countryiso3code": "DOM"}]
    monkeypatch.setattr(wgi, "fetch_wgi_indicator", lambda c, i, mrv=12: (rows, None))
    res = wgi_regulatory_sync(db)
    assert res["years"] == len(rows) - 1   # the null observation is not persisted
    payload = json.loads(db.query(AppSetting)
                         .filter(AppSetting.key == WGI_REGULATORY_KEY).one().value)
    assert "1999" not in payload["series"]


def test_wgi_sync_reports_upstream_failure_without_crashing(db, monkeypatch):
    import shared.data.wgi_client as wgi

    def boom(code, isos, mrv=12):
        raise RuntimeError("WB caído")

    monkeypatch.setattr(wgi, "fetch_wgi_indicator", boom)
    res = wgi_regulatory_sync(db)
    assert res["years"] == 0 and res["errors"] and "WB caído" in res["error"]
    # Best-effort: nothing half-written.
    assert db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).first() is None


# ── human_capital_sync ────────────────────────────────────────────
# Synthetic 0-1 inputs (transform-only; NOT domain data — no committed HCI fixture).
_HCI_ROWS = [{"date": "2020", "value": 0.5, "countryiso3code": "DOM"},
             {"date": "2018", "value": None, "countryiso3code": "DOM"}]


def test_hci_sync_scales_to_0_100_and_skips_nulls(db, monkeypatch):
    import shared.data.wgi_client as wgi
    monkeypatch.setattr(wgi, "fetch_wgi_indicator", lambda c, i, mrv=8: (_HCI_ROWS, "2020-09-16"))
    res = human_capital_sync(db)
    assert res["errors"] == [] and res["years"] == 1 and res["latest"] == 50.0
    payload = json.loads(db.query(AppSetting)
                         .filter(AppSetting.key == HUMAN_CAPITAL_KEY).one().value)
    assert payload["series"] == {"2020": 50.0}          # 0.5 → ×100, null dropped
    assert payload["source"] == "WB-HCI"


def test_hci_sync_upserts_in_place(db, monkeypatch):
    import shared.data.wgi_client as wgi
    monkeypatch.setattr(wgi, "fetch_wgi_indicator", lambda c, i, mrv=8: (_HCI_ROWS, None))
    human_capital_sync(db)
    human_capital_sync(db)
    assert db.query(AppSetting).filter(AppSetting.key == HUMAN_CAPITAL_KEY).count() == 1


def test_hci_sync_reports_upstream_failure_without_crashing(db, monkeypatch):
    import shared.data.wgi_client as wgi

    def boom(code, isos, mrv=8):
        raise RuntimeError("HCI no disponible")

    monkeypatch.setattr(wgi, "fetch_wgi_indicator", boom)
    res = human_capital_sync(db)
    assert res["years"] == 0 and res["errors"]
    assert db.query(AppSetting).filter(AppSetting.key == HUMAN_CAPITAL_KEY).first() is None
