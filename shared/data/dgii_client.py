"""Dirección General de Impuestos Internos (DGII) connector.

Taxpayer / fiscal registry signals.  Fixture-only for now; license must be
confirmed before any live ingestion, so ``license_ok`` stays False until then.
"""
from shared.data.base_client import FixtureBackedClient


class DGIIClient(FixtureBackedClient):
    source = "DGII"
    license = "por confirmar"
    license_ok = False
    fixture_file = "dgii.json"
    live_phase = "fase futura"


dgii_client = DGIIClient()
