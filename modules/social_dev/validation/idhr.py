"""PNUD regional Human Development Index (IDHr) — the external reference for the
IDM's convergent-validity check.

Real, official values for the 10 development regions, from the PNUD (UNDP)
"Mapa de Desarrollo Humano de la República Dominicana" (Oficina de Desarrollo
Humano), regional HDI table — reference data circa 2010 (the latest official
regional HDI published in a citable table). It is the best independent
development ranking of the same 10 planning regions (decree 710-04) the IDM uses.

Caveat (stated in the report): the IDHr reference year (~2010) predates the IDM's
latest period, but regional development rankings are structurally stable, so the
rank correlation is a valid convergent check, not a same-year comparison.
"""
from typing import Dict

SOURCE = "PNUD · Mapa de Desarrollo Humano RD (IDHr regional, ~2010)"

# region slug → IDHr value (0-1; higher = more development).
IDHR: Dict[str, float] = {
    "ozama": 0.607,
    "cibao_norte": 0.522,
    "cibao_sur": 0.500,
    "cibao_nordeste": 0.459,
    "yuma": 0.429,
    "higuamo": 0.413,
    "valdesia": 0.408,
    "cibao_noroeste": 0.379,
    "el_valle": 0.293,
    "enriquillo": 0.246,
}
