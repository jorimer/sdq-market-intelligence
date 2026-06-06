"""Banco Central de la República Dominicana (BCRD) connector.

Feeds `macro_monitor` (Eje 2) and the macro/external dimensions of the IRMP and
sector indices.  BCRD publishes official statistics openly; ``live`` mode (real
API ingestion) is built in Fase 2.
"""
from shared.data.base_client import FixtureBackedClient


class BCRDClient(FixtureBackedClient):
    source = "BCRD"
    license = "datos oficiales BCRD — uso público con cita"
    license_ok = True
    fixture_file = "bcrd.json"
    live_phase = "Fase 2"


bcrd_client = BCRDClient()
