"""ND-GAIN Country Index connector — national climate-resilience components.

The Notre Dame Global Adaptation Initiative (ND-GAIN) Country Index measures a
country's climate **vulnerability** (exposure, sensitivity, adaptive capacity) and
**readiness** (economic, governance, social) — country-year, ~187 countries,
CC-BY. It feeds three of the four IRC dimensions (physical, adaptive, governance);
transition (fossil/carbon) comes from energy/PEN (Gate C).

Public open data (CC-BY-3.0). The official download is behind a JS page, so we
ship a slim, versioned snapshot (latest year, the components we use) as a real
fixture — refreshed annually. Not synthetic: it is the actual ND-GAIN data,
attributed in the file's ``_meta``.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.data.ndgain")

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ndgain.json"

# Components we consume, oriented as ND-GAIN publishes them (0-1):
#   exposure/sensitivity → higher = WORSE (more vulnerable)
#   readiness/economic/governance/social → higher = BETTER
_COMPONENTS = ("exposure", "sensitivity", "readiness", "economic", "governance", "social")


class NDGAINClient:
    source = "ND-GAIN"
    license = "CC-BY-3.0 (University of Notre Dame)"
    license_ok = True

    def __init__(self) -> None:
        self._data: Optional[Dict] = None

    def _load(self) -> Dict:
        if self._data is None:
            if not _FIXTURE.exists():
                logger.warning("ND-GAIN fixture ausente: %s", _FIXTURE)
                self._data = {"countries": {}, "_meta": {}}
            else:
                with _FIXTURE.open(encoding="utf-8") as fh:
                    self._data = json.load(fh)
        return self._data

    def reference_year(self) -> Optional[str]:
        return (self._load().get("_meta") or {}).get("reference_year")

    def country(self, iso3: str) -> Dict[str, float]:
        """Raw ND-GAIN components for one country (``{component: value}``)."""
        return dict(self._load().get("countries", {}).get(iso3.upper(), {}))

    def panel(self, iso3_list: List[str]) -> Dict[str, Dict[str, float]]:
        """``{iso3: {component: value}}`` for the panel — only countries present
        with all consumed components (missing → omitted, never fabricated)."""
        out: Dict[str, Dict[str, float]] = {}
        countries = self._load().get("countries", {})
        for iso3 in iso3_list:
            row = countries.get(iso3.upper())
            if row and all(c in row for c in _COMPONENTS):
                out[iso3.upper()] = {c: float(row[c]) for c in _COMPONENTS}
        return out


ndgain_client = NDGAINClient()
