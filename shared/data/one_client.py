"""Oficina Nacional de Estadística (ONE) connector.

Feeds `social_dev` (Eje 5) and `esg_climate` (Eje 7): demographics, social,
gender, SDG, census and environmental statistics.  ``live`` mode in Fase 4.
"""
from shared.data.base_client import FixtureBackedClient


class ONEClient(FixtureBackedClient):
    source = "ONE"
    license = "datos oficiales ONE — uso público con cita"
    license_ok = True
    fixture_file = "one.json"
    live_phase = "Fase 4"


one_client = ONEClient()
