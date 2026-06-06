"""Dirección General de Aduanas (DGA) connector.

Customs / trade-by-product flows feeding `trade_intel` (Eje 6).  ``live`` mode
in Fase 5; fixture-backed until customs data access is wired.
"""
from shared.data.base_client import FixtureBackedClient


class DGAClient(FixtureBackedClient):
    source = "DGA"
    license = "por confirmar"
    license_ok = False
    fixture_file = "dga.json"
    live_phase = "Fase 5"


dga_client = DGAClient()
