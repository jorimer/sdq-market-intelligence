"""Panel LatAm + Caribe del IRMP para el backtest de la metodología.

Deriva del registro CANÓNICO ``shared.data.latam_peers`` — desde 2026-07 el producto
usa el mismo panel de 24 (antes el producto se quedaba en 5 y esto era "solo validación";
ya no: producto y backtest comparten la fuente única). Cada país lleva su ISO3 (World
Bank/IMF) y su FIPS 10-4 (GDELT usa FIPS, no ISO). Un FIPS errado da cero eventos GDELT →
el país se cae del outcome de gobernanza (nunca se fabrica) y el chequeo de cobertura lo
señala.
"""
from typing import Dict

from shared.data.latam_peers import PEERS

# iso2 → {iso3 (World Bank/IMF), fips (GDELT ActionGeo)}
VALIDATION_PEERS: Dict[str, Dict[str, str]] = {
    p.iso2: {"iso3": p.iso3, "fips": p.fips} for p in PEERS
}


def iso3_map(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """iso2 → iso3."""
    return {k: v["iso3"] for k, v in peers.items()}


def fips_to_iso2(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """GDELT FIPS → iso2 (each FIPS is unique within the panel)."""
    return {v["fips"]: k for k, v in peers.items()}
