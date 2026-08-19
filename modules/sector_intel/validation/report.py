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
from shared.validation.metrics import mean_ic_with_t, spearman, spearman_bootstrap_ci


def _partial_spearman(x: List[float], y: List[float], z: List[float]) -> Optional[float]:
    """First-order partial rank correlation of x,y controlling for z."""
    rxy, rxz, ryz = spearman(x, y), spearman(x, z), spearman(y, z)
    if None in (rxy, rxz, ryz):
        return None
    denom = ((1 - rxz ** 2) * (1 - ryz ** 2)) ** 0.5
    return round((rxy - rxz * ryz) / denom, 3) if denom > 0 else None


def _quintile_spread_by_year(by_year: Dict[str, List[Dict]], k: int = 5) -> Optional[Dict]:
    """Top-vs-bottom IAI k-tile outcome spread computed WITHIN each year, then averaged.

    Ranking the branches among themselves each year avoids the cross-year mixing of
    stacking all rows together (the same year-clustering bias as the pooled IC, in
    smaller magnitude). Years with fewer than ``k`` branches are skipped.
    """
    tops: List[float] = []
    bottoms: List[float] = []
    spreads: List[float] = []
    for rows in by_year.values():
        if len(rows) < k:
            continue
        pairs = sorted((r["iai_score"], r["emp_growth_next"]) for r in rows)
        size = len(pairs) // k
        bottom = [o for _i, o in pairs[:size]]
        top = [o for _i, o in pairs[-size:]]
        tops.append(sum(top) / len(top))
        bottoms.append(sum(bottom) / len(bottom))
        spreads.append(tops[-1] - bottoms[-1])
    if not spreads:
        return None
    return {"top_iai_mean_growth": round(sum(tops) / len(tops), 2),
            "bottom_iai_mean_growth": round(sum(bottoms) / len(bottoms), 2),
            "spread": round(sum(spreads) / len(spreads), 2),
            "n_years": len(spreads)}


# La prosa vive en constantes; las CUENTAS del panel se computan. Escrito a mano decía
# «10 ramas» en dos lugares: cierto hoy, y falso el día que el ENCFT publique una rama más o
# que una se quede sin empleo comparable. Es la misma forma del defecto que el IRMP publicó
# («5 países» contra un panel de 24) y que el eje social tenía latente.
_METODO_TITULAR = (
    "Validación DIRECCIONAL, no grado-Basilea. Mide si el IAI en T ordena el crecimiento del "
    "empleo formal por rama en T+1 (IC de rango de Spearman). TITULAR: el IC MEDIO de las "
    "cross-sections anuales, con CI de Student-t sobre la serie de IC por año (la inferencia "
    "correcta para un panel sector-año, que respeta el clustering por año). El IC apilado "
    "(pooled) se reporta como SECUNDARIO: su bootstrap remuestrea pares como si fueran "
    "independientes y sobrestima la precisión. El outcome es un CAMBIO (Δ% empleo), no un "
    "nivel; aun así se reporta el IC PARCIAL controlando por el crecimiento del sector en T "
    "(sector_growth_T) para acotar la inercia serial."
)
_METODO_RESOLUCION = (
    "manufactura local, zonas francas y minería colapsan en «Industrias» del lado del empleo"
)
_METODO_POTENCIA = (
    "Un IC inconcluso por potencia es un resultado válido y se muestra tal cual."
)


def _resolucion(n_ramas: int) -> str:
    return (f"{n_ramas} ramas de actividad (ENCFT); IAI agregado por tamaño del sector")


def _disclaimer(n_ramas: int, n_years: int) -> str:
    """Arma el disclaimer con el tamaño REAL del panel, no con el que tenía al escribirse."""
    return (
        f"{_METODO_TITULAR} Resolución: {n_ramas} ramas, NO 17 — {_METODO_RESOLUCION}. "
        f"Panel chico ({n_ramas} ramas × {n_years} años); con n por año ≈{n_ramas} el IC "
        f"mínimo detectable es alto. {_METODO_POTENCIA}"
    )


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
    # SECONDARY (kept for transparency): the pooled Spearman over the ~60 stacked
    # sector-year pairs. Its bootstrap resamples pairs as if independent — they are
    # clustered by year (common macro shock) and sector — so it understates the CI.
    pooled_rho, pooled_lo, pooled_hi = spearman_bootstrap_ci(iai, out)

    by_year: Dict[str, List[Dict]] = {}
    for r in labeled:
        by_year.setdefault(r["period"], []).append(r)
    per_year = []
    for yr in sorted(by_year):
        rows = by_year[yr]
        rr = spearman([x["iai_score"] for x in rows], [x["emp_growth_next"] for x in rows])
        per_year.append({"year": yr, "n": len(rows),
                         "spearman": None if rr is None else round(rr, 3)})

    # HEADLINE: the classical panel IC — mean of the per-year cross-sectional rank ICs
    # with a Student-t CI over the series of yearly ICs (correct clustering by year).
    yearly = [p["spearman"] for p in per_year if p["spearman"] is not None]
    ic = mean_ic_with_t(yearly)

    # partial control on the rows where sector_growth_T exists (the first panel year
    # has no prior year → no growth); reported with its own n.
    g_rows = [r for r in labeled if r.get("sector_growth") is not None]
    partial = partial_n = None
    if len(g_rows) >= 4:
        partial = _partial_spearman([r["iai_score"] for r in g_rows],
                                    [r["emp_growth_next"] for r in g_rows],
                                    [r["sector_growth"] for r in g_rows])
        partial_n = len(g_rows)

    n_ramas = len({r["branch"] for r in labeled})
    return {
        "has_data": True,
        "outcome": "crecimiento del empleo formal (Δ% T+1, ENCFT)",
        "resolution": _resolucion(n_ramas),
        "n_observations": len(labeled),
        "n_branches": n_ramas,
        "years": [min(by_year), max(by_year)],
        # HEADLINE — mean yearly IC with a Student-t CI over the series of yearly ICs.
        "mean_yearly_ic": ic["mean_ic"] if ic else None,
        "n_years": ic["n_years"] if ic else len(yearly),
        "ic_t_stat": ic["t_stat"] if ic else None,
        "ic_ci": [ic["ci_lo"], ic["ci_hi"]] if ic else [None, None],
        # SECONDARY — pooled stacked Spearman; kept visible but NOT the headline.
        "spearman_pooled": None if pooled_rho is None else round(pooled_rho, 3),
        "spearman_pooled_ci": [None if pooled_lo is None else round(pooled_lo, 3),
                               None if pooled_hi is None else round(pooled_hi, 3)],
        "spearman_pooled_note": ("pooled sobre los pares sector-año apilados (sin "
                                 "clustering año/sector) — sobrestima la precisión; "
                                 "el titular es el IC medio anual con t"),
        "spearman_partial_growth": partial,
        "spearman_partial_n": partial_n,
        "by_year": per_year,
        "quintile_spread": _quintile_spread_by_year(by_year),
        "disclaimer": _disclaimer(n_ramas, ic["n_years"] if ic else len(yearly)),
    }
