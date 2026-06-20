"""Gate-E sectorial report — does IAI_T rank next-year employment growth?

Spearman rank IC (with a bootstrap CI) between the branch IAI in T and Δemployment
in T+1, plus the rank IC per year and the growth spread between the top and bottom
IAI quintiles. Because the IAI contains ``sector_growth_T`` (and a level proxy of
employment), the report also gives the PARTIAL rank IC controlling for
``sector_growth_T`` — if the signal survives, it isn't merely serial inertia.

Honest by construction: the panel is small (~10 branches × ~6 year-pairs), so this
is a DIRECTIONAL validation reported with its n and CI, never grade-Basel. A weak
or null IC is a valid result and is shown as-is, not massaged.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.validation.historical import build_iai_panel
from modules.sector_intel.validation.outcomes import employment_by_branch, label_panel
from shared.validation.metrics import spearman, spearman_bootstrap_ci


def _partial_spearman(x: List[float], y: List[float], z: List[float]) -> Optional[float]:
    """First-order partial rank correlation of x,y controlling for z."""
    rxy, rxz, ryz = spearman(x, y), spearman(x, z), spearman(y, z)
    if None in (rxy, rxz, ryz):
        return None
    denom = ((1 - rxz ** 2) * (1 - ryz ** 2)) ** 0.5
    return round((rxy - rxz * ryz) / denom, 3) if denom > 0 else None


def _quintile_spread(iai: List[float], out: List[float], k: int = 5) -> Optional[Dict]:
    """Mean outcome in the top vs bottom IAI quintile (k-tile), and their spread."""
    n = len(iai)
    if n < k:
        return None
    pairs = sorted(zip(iai, out))
    size = n // k
    bottom = [o for _i, o in pairs[:size]]
    top = [o for _i, o in pairs[-size:]]
    tm, bm = sum(top) / len(top), sum(bottom) / len(bottom)
    return {"top_iai_mean_growth": round(tm, 2),
            "bottom_iai_mean_growth": round(bm, 2),
            "spread": round(tm - bm, 2), "tile_size": size}


def gate_e_report(db: Session) -> Dict:
    """Run the Gate-E backtest from the persisted IAI + ENCFT employment."""
    panel = build_iai_panel(db)
    labeled = label_panel(panel, employment_by_branch(db))
    if len(labeled) < 3:
        return {"has_data": False,
                "reason": "panel insuficiente con lookahead — corre sector-snapshot "
                          "y encft-empleo-sync antes del Gate E"}

    iai = [r["iai_score"] for r in labeled]
    out = [r["emp_growth_next"] for r in labeled]
    rho, lo, hi = spearman_bootstrap_ci(iai, out)

    by_year: Dict[str, List[Dict]] = {}
    for r in labeled:
        by_year.setdefault(r["period"], []).append(r)
    per_year = []
    for yr in sorted(by_year):
        rows = by_year[yr]
        rr = spearman([x["iai_score"] for x in rows], [x["emp_growth_next"] for x in rows])
        per_year.append({"year": yr, "n": len(rows),
                         "spearman": None if rr is None else round(rr, 3)})

    # partial control on the rows where sector_growth_T exists (the first panel year
    # has no prior year → no growth); reported with its own n.
    g_rows = [r for r in labeled if r.get("sector_growth") is not None]
    partial = partial_n = None
    if len(g_rows) >= 4:
        partial = _partial_spearman([r["iai_score"] for r in g_rows],
                                    [r["emp_growth_next"] for r in g_rows],
                                    [r["sector_growth"] for r in g_rows])
        partial_n = len(g_rows)

    return {
        "has_data": True,
        "outcome": "crecimiento del empleo formal (Δ% T+1, ENCFT)",
        "resolution": "10 ramas de actividad (ENCFT); IAI agregado por tamaño del sector",
        "n_observations": len(labeled),
        "n_branches": len({r["branch"] for r in labeled}),
        "years": [min(by_year), max(by_year)],
        "spearman": None if rho is None else round(rho, 3),
        "spearman_ci": [None if lo is None else round(lo, 3),
                        None if hi is None else round(hi, 3)],
        "spearman_partial_growth": partial,
        "spearman_partial_n": partial_n,
        "by_year": per_year,
        "quintile_spread": _quintile_spread(iai, out),
        "disclaimer": (
            "Validación DIRECCIONAL, no grado-Basilea. Mide si el IAI en T ordena el "
            "crecimiento del empleo formal por rama en T+1 (IC de rango de Spearman). "
            "El outcome es un CAMBIO (Δ% empleo), no un nivel, así que no es "
            "trivialmente circular con el nivel de empleo que el IAI contiene; aun así "
            "se reporta el IC PARCIAL controlando por el crecimiento del sector en T "
            "(sector_growth_T) para acotar la inercia serial. Panel chico (~10 ramas × "
            "~6 pares de años); se reporta con su n e IC. Un IC débil o nulo es un "
            "resultado válido y se muestra tal cual."
        ),
    }
