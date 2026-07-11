"""Registro canónico del panel LatAm + Caribe del IRMP — una sola fuente de verdad.

Antes el peer set del PRODUCTO estaba fijo en 5 países (Doctrina de Casa "set regional
focalizado"), duplicado en varios módulos (WDI, GDELT, snapshot), mientras el backtest
validaba sobre 24. Eso dejaba el panel del producto hueco (2 Caribe + 3 Centroamérica).
Este registro unifica los 24 (todos con gobernanza WGI-2025 y macro/externo WDI reales)
y es la fuente única que consumen el sync WDI/IMF, el de eventos GDELT (por su FIPS) y el
snapshot (nombre + región). Los países sin dato completo (p.ej. sin rating soberano) se
puntúan con las variables que tengan; el guard salta los parciales, nunca fabrica.
"""
from typing import Dict, List, NamedTuple, Optional


class Peer(NamedTuple):
    iso2: str        # nuestra clave (CountryVariable.iso_code)
    iso3: str        # World Bank / IMF
    fips: str        # GDELT FIPS 10-4 (V2Locations)
    name: str
    region: str


# Orden: el set regional focalizado primero (RD + su vecindario), luego el resto de
# Sudamérica — sin cambiar la clave iso2 de nadie.
PEERS: List[Peer] = [
    Peer("DO", "DOM", "DR", "República Dominicana", "Caribe"),
    Peer("CR", "CRI", "CS", "Costa Rica", "Centroamérica"),
    Peer("PA", "PAN", "PM", "Panamá", "Centroamérica"),
    Peer("GT", "GTM", "GT", "Guatemala", "Centroamérica"),
    Peer("JM", "JAM", "JM", "Jamaica", "Caribe"),
    Peer("SV", "SLV", "ES", "El Salvador", "Centroamérica"),
    Peer("HN", "HND", "HO", "Honduras", "Centroamérica"),
    Peer("NI", "NIC", "NU", "Nicaragua", "Centroamérica"),
    Peer("BZ", "BLZ", "BH", "Belice", "Centroamérica"),
    Peer("TT", "TTO", "TD", "Trinidad y Tobago", "Caribe"),
    Peer("HT", "HTI", "HA", "Haití", "Caribe"),
    Peer("MX", "MEX", "MX", "México", "Norteamérica"),
    Peer("AR", "ARG", "AR", "Argentina", "Sudamérica"),
    Peer("BO", "BOL", "BL", "Bolivia", "Sudamérica"),
    Peer("BR", "BRA", "BR", "Brasil", "Sudamérica"),
    Peer("CL", "CHL", "CI", "Chile", "Sudamérica"),
    Peer("CO", "COL", "CO", "Colombia", "Sudamérica"),
    Peer("EC", "ECU", "EC", "Ecuador", "Sudamérica"),
    Peer("PY", "PRY", "PA", "Paraguay", "Sudamérica"),
    Peer("PE", "PER", "PE", "Perú", "Sudamérica"),
    Peer("UY", "URY", "UY", "Uruguay", "Sudamérica"),
    Peer("VE", "VEN", "VE", "Venezuela", "Sudamérica"),
    Peer("GY", "GUY", "GY", "Guyana", "Sudamérica"),
    Peer("SR", "SUR", "NS", "Surinam", "Sudamérica"),
]

_BY_ISO2: Dict[str, Peer] = {p.iso2: p for p in PEERS}


def iso3_by_iso2() -> Dict[str, str]:
    """``iso2 → iso3`` (World Bank/IMF)."""
    return {p.iso2: p.iso3 for p in PEERS}


def fips_to_iso2() -> Dict[str, str]:
    """``fips → iso2`` (GDELT). Cada FIPS es único dentro del panel."""
    return {p.fips: p.iso2 for p in PEERS}


def names() -> Dict[str, str]:
    """``iso2 → nombre``."""
    return {p.iso2: p.name for p in PEERS}


def regions() -> Dict[str, str]:
    """``iso2 → región``."""
    return {p.iso2: p.region for p in PEERS}


def peer(iso2: str) -> Optional[Peer]:
    return _BY_ISO2.get(iso2)
