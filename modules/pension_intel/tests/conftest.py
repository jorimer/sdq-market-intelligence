"""Shared test fixtures for the pension_intel module."""
import pytest


@pytest.fixture(autouse=True)
def _stub_sipen_ckan(monkeypatch):
    """Keep every pension test hermetic: the SIPEN sync now also pulls live national
    series from CKAN (network). Stub it to empty so tests run offline on the fixture
    floor; a test that needs CKAN data re-stubs it locally with fake Records."""
    monkeypatch.setattr(
        "modules.pension_intel.sipen_sync.fetch_sipen_ckan", lambda period=None: []
    )
