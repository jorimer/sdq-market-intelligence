"""IAI panel for the Gate-E backtest, aggregated to the 10 ENCFT activity branches.

The IAI is computed per BCRD-17 slug, but the employment outcome lives at the
ONE's 10-branch resolution. So each branch's IAI for a period is the size-weighted
mean of its member slugs' persisted ``iai_score`` (weights = ``sector_size`` from
``si_variables``). Point-in-time: reads the IAI already persisted by the snapshot
backfill — it never recomputes with future data. ``sector_growth`` is aggregated
the same way to control the circularity in the report.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.models.models import SectorScore, SectorVariable
from shared.data.sector_crosswalk import ENCFT_BRANCHES


def _by_slug_period(db: Session, variable: str) -> Dict[tuple, float]:
    """``{(slug, period): value}`` for a sector-dimension variable in si_variables."""
    out: Dict[tuple, float] = {}
    rows = (db.query(SectorVariable)
            .filter(SectorVariable.dimension == "sector",
                    SectorVariable.variable == variable).all())
    for r in rows:
        if r.value is not None and r.period:
            out[(r.sector_code, r.period)] = r.value
    return out


def _weighted(members, period, value_map, size) -> Optional[float]:
    """Size-weighted mean of *members*' *value_map* at *period* (None if no data)."""
    num = den = 0.0
    for slug in members:
        w, v = size.get((slug, period)), value_map.get((slug, period))
        if w is None or v is None or w <= 0:
            continue
        num += v * w
        den += w
    return num / den if den > 0 else None


def build_iai_panel(db: Session) -> List[Dict]:
    """One row per (branch, period): ``{branch, period, iai_score, sector_growth}``.

    Drops a (branch, period) with no member IAI/size data, never fabricated.
    """
    iai = {(s.sector_code, s.period): s.iai_score
           for s in db.query(SectorScore).all() if s.iai_score is not None}
    size = _by_slug_period(db, "sector_size")
    growth = _by_slug_period(db, "sector_growth")
    periods = sorted({p for (_s, p) in iai})

    panel: List[Dict] = []
    for branch in ENCFT_BRANCHES:
        for period in periods:
            score = _weighted(branch.members, period, iai, size)
            if score is None:
                continue
            panel.append({
                "branch": branch.key,
                "period": period,
                "iai_score": round(score, 3),
                "sector_growth": _weighted(branch.members, period, growth, size),
            })
    return panel
