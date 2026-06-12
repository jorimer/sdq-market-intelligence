"""Tests for the shared data layer: lineage, license gating, fixtures."""
from datetime import date

import pytest

from shared.data import (
    LicenseError,
    Record,
    bcrd_client,
    dga_client,
)
from shared.data.lineage import Lineage


class TestLineage:
    def test_publication_lag_days(self):
        lin = Lineage(
            source="BCRD", license="x",
            published_at=date(2025, 1, 1), fetched_at=date(2025, 1, 11),
        )
        assert lin.publication_lag_days == 10

    def test_lag_none_when_dates_missing(self):
        assert Lineage(source="X", license="y").publication_lag_days is None


class TestLicenseGate:
    def test_unlicensed_source_blocks_fetch(self):
        # DGA license is unconfirmed → license_ok = False
        with pytest.raises(LicenseError):
            dga_client.fetch()

    def test_licensed_source_allows_fetch(self):
        records = bcrd_client.fetch()
        assert records  # fixture has data
        assert all(isinstance(r, Record) for r in records)


class TestFixtureFetch:
    def test_preserves_missing_as_none(self):
        records = bcrd_client.fetch(series="gdp_growth")
        by_period = {r.period: r.value for r in records}
        assert by_period["2025-Q2"] is None       # null in fixture, not interpolated
        assert by_period["2024-Q3"] == 5.1

    def test_filter_by_series_and_period(self):
        records = bcrd_client.fetch(series="inflation_yoy", period="2025-Q1")
        assert len(records) == 1
        assert records[0].series == "inflation_yoy"
        assert records[0].value == 3.9

    def test_records_carry_lineage(self):
        r = bcrd_client.fetch(series="gdp_growth")[0]
        assert r.lineage.source == "BCRD"
        assert r.lineage.fetched_at is not None

    def test_live_mode_without_token_degrades_gracefully(self):
        # BCRD live mode is implemented (Eje 2); with no token every variable
        # fails its credential check and we return [] rather than raising.
        from shared.data.bcrd_client import BCRDClient
        assert BCRDClient(mode="live").fetch() == []
