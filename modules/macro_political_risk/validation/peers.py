"""Broad LatAm + Caribbean panel for the IRMP methodology backtest.

This is a VALIDATION-ONLY peer set — it gives the backtest statistical power
(more cross-sectional units → narrower Gini CI) WITHOUT changing the product,
which stays the focused regional set (Doctrina de Casa). Each country carries its
World Bank ISO3 and its GDELT FIPS 10-4 code (V2/Events use FIPS, not ISO). FIPS
codes are best-effort and verified empirically: a wrong code yields zero GDELT
events → the country is simply dropped from the governance outcome (never
fabricated), and the coverage check surfaces it.
"""
from typing import Dict

# iso2 → {iso3 (World Bank/IMF), fips (GDELT ActionGeo)}
VALIDATION_PEERS: Dict[str, Dict[str, str]] = {
    "DO": {"iso3": "DOM", "fips": "DR"},
    "CR": {"iso3": "CRI", "fips": "CS"},
    "PA": {"iso3": "PAN", "fips": "PM"},
    "GT": {"iso3": "GTM", "fips": "GT"},
    "JM": {"iso3": "JAM", "fips": "JM"},
    "AR": {"iso3": "ARG", "fips": "AR"},
    "BO": {"iso3": "BOL", "fips": "BL"},
    "BR": {"iso3": "BRA", "fips": "BR"},
    "CL": {"iso3": "CHL", "fips": "CI"},
    "CO": {"iso3": "COL", "fips": "CO"},
    "EC": {"iso3": "ECU", "fips": "EC"},
    "SV": {"iso3": "SLV", "fips": "ES"},
    "HN": {"iso3": "HND", "fips": "HO"},
    "MX": {"iso3": "MEX", "fips": "MX"},
    "NI": {"iso3": "NIC", "fips": "NU"},
    "PY": {"iso3": "PRY", "fips": "PA"},
    "PE": {"iso3": "PER", "fips": "PE"},
    "TT": {"iso3": "TTO", "fips": "TD"},
    "UY": {"iso3": "URY", "fips": "UY"},
    "VE": {"iso3": "VEN", "fips": "VE"},
    "BZ": {"iso3": "BLZ", "fips": "BH"},
    "HT": {"iso3": "HTI", "fips": "HA"},
    "GY": {"iso3": "GUY", "fips": "GY"},
    "SR": {"iso3": "SUR", "fips": "NS"},
}


def iso3_map(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """iso2 → iso3."""
    return {k: v["iso3"] for k, v in peers.items()}


def fips_to_iso2(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """GDELT FIPS → iso2 (each FIPS is unique within the panel)."""
    return {v["fips"]: k for k, v in peers.items()}
