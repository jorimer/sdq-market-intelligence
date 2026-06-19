"""Historical resilience panel for the Gate-E trade backtest.

Reconstructs the resilience score (export-concentration HHI + import dependency)
for every peer and year from the committed Comtrade panel, reusing the SAME pure
scorer the product uses (``compute_trade_scores``). Unlike the IRMP, the score is
absolute (0-100), not cross-sectionally normalized, so each (country, year) is
scored independently from its own flows — no peer-set leakage between rows.

A year is scored only when BOTH sides are present (export chapters AND a total
import value); otherwise import dependency would silently read as zero. Missing →
the row is dropped, never fabricated.
"""
from typing import Dict, List, Optional

from modules.trade_intel.scoring.concentration import compute_trade_scores
from shared.data import comtrade_client as cc

# Resilience bands — same thresholds as the product UI (bandFor, higher = stronger).
# Ordered best → worst so the realized-shock rate should RISE across them.
BAND_ORDER = ["Fuerte", "Sólido", "Vigilar", "Débil"]


def resilience_band(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score >= 85:
        return "Fuerte"
    if score >= 70:
        return "Sólido"
    if score >= 55:
        return "Vigilar"
    return "Débil"


def _flows_from(country_year: Dict) -> List[Dict]:
    """Comtrade {exports_by_chapter, imports_total} → scorer flow list."""
    flows: List[Dict] = []
    for chapter, val in (country_year.get("exports_by_chapter") or {}).items():
        flows.append({"product": chapter, "direction": "export", "value": val})
    im = country_year.get("imports_total")
    if im is not None:
        flows.append({"product": "TOTAL", "direction": "import", "value": im})
    return flows


def build_panel(dataset: Optional[Dict] = None) -> List[Dict]:
    """One row per (country, year): ``{iso, year, resilience_score, band, total_exports}``.

    Iterates the dataset's trade matrix (the fixture only holds validation peers).
    """
    if dataset is None:
        dataset = cc.load_panel()
    trade = (dataset or {}).get("trade", {})
    panel: List[Dict] = []
    for iso2, years in trade.items():
        for year_str, cy in sorted(years.items()):
            if not (cy.get("exports_by_chapter") and cy.get("imports_total") is not None):
                continue  # need both sides for a valid resilience score
            sc = compute_trade_scores(_flows_from(cy))
            score = sc.get("resilience_score")
            if score is None:
                continue
            panel.append({
                "iso": iso2,
                "year": int(year_str),
                "resilience_score": score,
                "band": resilience_band(score),
                "total_exports": sc.get("total_exports"),
            })
    return panel


def exports_by_year(panel: List[Dict]) -> Dict[str, Dict[int, float]]:
    """``{iso: {year: total_exports}}`` — input for the export-collapse outcome."""
    out: Dict[str, Dict[int, float]] = {}
    for r in panel:
        out.setdefault(r["iso"], {})[r["year"]] = r["total_exports"]
    return out
