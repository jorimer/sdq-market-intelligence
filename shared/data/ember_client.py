"""Ember connector — power-sector transition metrics per country.

Ember's Yearly Electricity Data (CC-BY-4.0) gives, per country-year, the fossil
share of electricity generation (%) and the carbon intensity of the grid
(gCO2/kWh). Both feed the IRC transition-risk dimension panel-wide (Gate C),
with one consistent methodology across the panel — so the cross-country min-max
is meaningful. Public open data; the DR value (~76% fossil) cross-checks the
CNE PEN's electricity matrix.
"""
import csv
import io
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sdq.data.ember")

_CSV_URL = "https://files.ember-energy.org/public-downloads/yearly_full_release_long_format.csv"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}


def _classify(row: Dict[str, str]) -> Optional[str]:
    """Map an Ember long-format row to our transition variable, or None."""
    cat, sub, var, unit = (row.get("Category"), row.get("Subcategory"),
                           row.get("Variable"), row.get("Unit"))
    if cat == "Electricity generation" and sub == "Aggregate fuel" and var == "Fossil" and unit == "%":
        return "fossil_dependence"
    if sub == "CO2 intensity" and var == "CO2 intensity" and unit == "gCO2/kWh":
        return "carbon_intensity"
    return None


def parse_transition(csv_text: str, iso3_list: List[str]) -> Dict[str, Dict[str, float]]:
    """``{iso3: {fossil_dependence, carbon_intensity}}`` — latest year per country,
    restricted to *iso3_list*. Missing → omitted (never fabricated)."""
    want = {i.upper() for i in iso3_list}
    # iso3 -> var -> (year, value)
    best: Dict[str, Dict[str, Tuple[int, float]]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        iso = (row.get("ISO 3 code") or "").upper()
        if iso not in want:
            continue
        key = _classify(row)
        if not key:
            continue
        try:
            year = int(row["Year"])
            value = float(row["Value"])
        except (ValueError, TypeError, KeyError):
            continue
        cur = best.setdefault(iso, {}).get(key)
        if cur is None or year > cur[0]:
            best[iso][key] = (year, value)
    return {
        iso: {k: v for k, (_, v) in vals.items()}
        for iso, vals in best.items()
    }


class EmberClient:
    source = "Ember"
    license = "CC-BY-4.0 (Ember)"
    license_ok = True

    def fetch_transition(self, iso3_list: List[str]) -> Dict[str, Dict[str, float]]:
        """Download Ember Yearly Electricity Data and extract the transition metrics
        for the panel. Raises on network failure (caller treats Gate C best-effort)."""
        import httpx

        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            text = http.get(_CSV_URL).text
        return parse_transition(text, iso3_list)


ember_client = EmberClient()
