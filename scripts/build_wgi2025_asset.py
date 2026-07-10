"""Build the canonical WGI-2025 data asset from the official reproducibility file.

Reads the World Bank's ``wgidataset_with_sourcedata-2025.xlsx`` (the December 2025
methodology revision, with the absolute 0-100 scale, confidence intervals, source
counts and the 35 underlying source means) and emits a compact JSON asset scoped
to the IRMP regional panel.

Output shape (regenerable; committed under the module's data/ dir):

    {
      "meta": {"source": "WGI 2025", "license": "World Bank Open Data (CC-BY 4.0)",
               "generated_from": "wgidataset_with_sourcedata-2025.xlsx",
               "years": [1996, ..., 2024], "economies": ["DOM", ...]},
      "data": {
        "<iso3>": {
          "<wgi_variable>": {
            "<year>": {"score": 53.8, "se": 2.2, "ci_lo": 49.5, "ci_hi": 58.2,
                        "n_sources": 12, "sources": {"BTI": 0.42, "EIU": -0.1, ...}}
          }
        }
      }
    }

Usage:  python scripts/build_wgi2025_asset.py <path-to-xlsx> [out.json]
The xlsx is NOT committed (10 MB); the slim JSON asset is.
"""
import json
import sys
from pathlib import Path

import openpyxl

# WGI sheet/dimension code → our canonical IRMP variable name.
DIM_TO_VAR = {
    "va": "wgi_voice_accountability",
    "pv": "wgi_political_stability",
    "ge": "wgi_gov_effectiveness",
    "rq": "wgi_regulatory_quality",
    "rl": "wgi_rule_of_law",
    "cc": "wgi_control_corruption",
}

# The 35 underlying source codes, in column order (cols 16..50 of each sheet).
SOURCE_CODES = [
    "ADB", "AFR", "ARB", "ASB", "ASD", "BPS", "BTI", "CCR", "EBR", "EIU",
    "EQI", "EUB", "FRH", "GCB", "GCS", "GII", "GWP", "HER", "HRM", "HUM",
    "IFD", "IJT", "IRP", "LBO", "MSI", "OBI", "PIA", "PRS", "RSF", "VAB",
    "VDM", "WBS", "WCY", "WJP", "WMO",
]

# IRMP regional panel (iso3) — mirrors modules/macro_political_risk/validation/peers.py
# (the broad LatAm + Caribbean set the methodology was validated on).
PANEL_ISO3 = [
    "DOM", "CRI", "PAN", "GTM", "JAM", "ARG", "BOL", "BRA", "CHL", "COL",
    "ECU", "SLV", "HND", "MEX", "NIC", "PRY", "PER", "TTO", "URY", "VEN",
    "BLZ", "HTI", "GUY", "SUR",
]

# Column indices in the source-data sheets (0-based).
C_CODE, C_YEAR, C_NSRC = 2, 5, 7
C_SCORE, C_SE, C_CI_LO, C_CI_HI = 12, 13, 14, 15
C_SRC0 = 16


def _num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def build(xlsx_path: str) -> dict:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    panel = set(PANEL_ISO3)
    data: dict = {}
    years: set = set()
    for dim, var in DIM_TO_VAR.items():
        ws = wb[dim]
        for r in ws.iter_rows(min_row=2, values_only=True):
            iso3 = r[C_CODE]
            if iso3 not in panel:
                continue
            year = r[C_YEAR]
            score = _num(r[C_SCORE])
            if year is None or score is None:
                continue
            years.add(int(year))
            sources = {}
            for i, code in enumerate(SOURCE_CODES):
                val = _num(r[C_SRC0 + i])
                if val is not None:
                    sources[code] = val
            entry = {
                "score": score,
                "se": _num(r[C_SE]),
                "ci_lo": _num(r[C_CI_LO]),
                "ci_hi": _num(r[C_CI_HI]),
                "n_sources": int(r[C_NSRC]) if r[C_NSRC] is not None else len(sources),
                "sources": sources,
            }
            data.setdefault(iso3, {}).setdefault(var, {})[str(int(year))] = entry
    wb.close()
    return {
        "meta": {
            "source": "WGI 2025 (revised methodology)",
            "license": "World Bank Open Data (CC-BY 4.0)",
            "generated_from": "wgidataset_with_sourcedata-2025.xlsx",
            "scale": "absolute 0-100 (higher = better governance)",
            "years": sorted(years),
            "economies": sorted(data.keys()),
            "variables": sorted(DIM_TO_VAR.values()),
        },
        "data": data,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    xlsx = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(
        Path(__file__).resolve().parent.parent
        / "modules/macro_political_risk/data/wgi2025.json"
    )
    asset = build(xlsx)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(asset, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    m = asset["meta"]
    print(f"Wrote {out}")
    print(f"  economies: {len(m['economies'])}  years: {m['years'][0]}-{m['years'][-1]} "
          f"({len(m['years'])})  variables: {len(m['variables'])}")
    print(f"  size: {Path(out).stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
