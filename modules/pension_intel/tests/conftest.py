"""Shared test fixtures for the pension_intel module."""
import pytest


@pytest.fixture(autouse=True)
def _stub_sipen_live(monkeypatch):
    """Keep every pension test hermetic: the SIPEN sync pulls live national series from
    CKAN and live rentabilidad from the Estadística Previsional XLSX (both network). Stub
    both to empty so tests run offline on the fixture floor; a test that needs the live
    data re-stubs it locally with fake Records."""
    monkeypatch.setattr(
        "modules.pension_intel.sipen_sync.fetch_sipen_ckan", lambda period=None: []
    )
    monkeypatch.setattr(
        "modules.pension_intel.sipen_sync.fetch_sipen_rentabilidad",
        lambda period=None: ([], []),
    )
