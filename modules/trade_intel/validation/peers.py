"""Broad LatAm + Caribbean panel for the trade-resilience methodology backtest.

VALIDATION-ONLY peer set: it gives the backtest statistical power (more
cross-sectional units → narrower Gini CI) WITHOUT changing the product, which
stays RD-focused. Each country carries its World Bank ISO3 (WDI outcomes) and its
UN Comtrade M49 reporter code (trade flows). Codes are verified empirically: a
wrong code yields an empty trade pull → the country is dropped from the panel
(never fabricated) and surfaced in the coverage block.

Deliberately the same 24-country universe as the IRMP backtest, for cross-axis
coherence. Duplicated here (not imported) to respect module independence.
"""
from typing import Dict

# iso2 → {iso3 (World Bank/IMF), m49 (UN Comtrade reporterCode)}
VALIDATION_PEERS: Dict[str, Dict[str, str]] = {
    "DO": {"iso3": "DOM", "m49": "214"},
    "CR": {"iso3": "CRI", "m49": "188"},
    "PA": {"iso3": "PAN", "m49": "591"},
    "GT": {"iso3": "GTM", "m49": "320"},
    "JM": {"iso3": "JAM", "m49": "388"},
    "AR": {"iso3": "ARG", "m49": "32"},
    "BO": {"iso3": "BOL", "m49": "68"},
    "BR": {"iso3": "BRA", "m49": "76"},
    "CL": {"iso3": "CHL", "m49": "152"},
    "CO": {"iso3": "COL", "m49": "170"},
    "EC": {"iso3": "ECU", "m49": "218"},
    "SV": {"iso3": "SLV", "m49": "222"},
    "HN": {"iso3": "HND", "m49": "340"},
    "MX": {"iso3": "MEX", "m49": "484"},
    "NI": {"iso3": "NIC", "m49": "558"},
    "PY": {"iso3": "PRY", "m49": "600"},
    "PE": {"iso3": "PER", "m49": "604"},
    "TT": {"iso3": "TTO", "m49": "780"},
    "UY": {"iso3": "URY", "m49": "858"},
    "VE": {"iso3": "VEN", "m49": "862"},
    "BZ": {"iso3": "BLZ", "m49": "84"},
    "HT": {"iso3": "HTI", "m49": "332"},
    "GY": {"iso3": "GUY", "m49": "328"},
    "SR": {"iso3": "SUR", "m49": "740"},
}

# Display names (Spanish) for the panel coverage UI.
COUNTRY_NAMES: Dict[str, str] = {
    "DO": "Rep. Dominicana", "CR": "Costa Rica", "PA": "Panamá", "GT": "Guatemala",
    "JM": "Jamaica", "AR": "Argentina", "BO": "Bolivia", "BR": "Brasil", "CL": "Chile",
    "CO": "Colombia", "EC": "Ecuador", "SV": "El Salvador", "HN": "Honduras",
    "MX": "México", "NI": "Nicaragua", "PY": "Paraguay", "PE": "Perú",
    "TT": "Trinidad y Tobago", "UY": "Uruguay", "VE": "Venezuela", "BZ": "Belice",
    "HT": "Haití", "GY": "Guyana", "SR": "Surinam",
}


def iso3_map(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """iso2 → iso3."""
    return {k: v["iso3"] for k, v in peers.items()}


def m49_map(peers: Dict[str, Dict[str, str]] = VALIDATION_PEERS) -> Dict[str, str]:
    """iso2 → UN Comtrade M49 reporter code."""
    return {k: v["m49"] for k, v in peers.items()}
