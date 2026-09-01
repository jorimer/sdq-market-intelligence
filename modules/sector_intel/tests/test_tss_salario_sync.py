"""Tests for the TSS salary sync → operating_cost AppSetting (Gate-E PR-4)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.tss_salary import TSSSalaryClient, TSSSalaryError
from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — register app_setting table
from shared.reference.sector_variables import SectorVariable  # noqa: F401 — register tables
from modules.sector_intel.sectors_sync import (
    OPERATING_COST_KEY,
    latest_complete_year,
    tss_salario_sync,
)


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


def test_latest_complete_year_skips_the_current_partial_year():
    assert latest_complete_year(["2024", "2025", "2026"], 2026) == "2025"
    assert latest_complete_year(["2024", "2025"], 2026) == "2025"      # all complete → max
    assert latest_complete_year(["2026"], 2026) == "2026"              # only partial → fall back
    assert latest_complete_year([], 2026) is None


def test_sync_persists_per_slug_operating_cost(db, monkeypatch):
    monkeypatch.setattr(TSSSalaryClient, "_fetch_live", TSSSalaryClient._fetch_fixture)
    res = tss_salario_sync(db)
    assert res["errors"] == []
    assert res["slugs"] == 17                       # crosswalk covers all 17
    assert res["missing"] == []
    row = db.query(AppSetting).filter(AppSetting.key == OPERATING_COST_KEY).first()
    payload = json.loads(row.value)
    series = payload["series"]
    assert set(series) == {  # every BCRD-17 slug present, keyed by slug (short, ≤40)
        "agropecuario", "mineria", "manufactura_local", "zonas_francas", "construccion",
        "energia", "comercio", "turismo", "transporte", "comunicaciones", "financiero",
        "inmobiliario", "ensenanza", "salud", "administracion_publica",
        "servicios_profesionales", "otros_servicios",
    }
    assert all(len(k) <= 40 for k in series)        # no VARCHAR(40) truncation risk
    assert series["mineria"] > 70000                # verified TSS figure
    # shared-activity slugs carry the same declared-proxy value
    assert series["manufactura_local"] == series["zonas_francas"]
    assert series["otros_servicios"] == series["servicios_profesionales"]


def test_sync_idempotent(db, monkeypatch):
    monkeypatch.setattr(TSSSalaryClient, "_fetch_live", TSSSalaryClient._fetch_fixture)
    tss_salario_sync(db)
    tss_salario_sync(db)
    assert db.query(AppSetting).filter(AppSetting.key == OPERATING_COST_KEY).count() == 1


def test_sync_best_effort_on_failure(db, monkeypatch):
    def _boom(self, series=None, period=None):
        raise TSSSalaryError("Power BI caído")
    monkeypatch.setattr(TSSSalaryClient, "_fetch_live", _boom)
    res = tss_salario_sync(db)                       # must not raise
    assert res["slugs"] == 0 and res["errors"]
    assert db.query(AppSetting).filter(AppSetting.key == OPERATING_COST_KEY).count() == 0
