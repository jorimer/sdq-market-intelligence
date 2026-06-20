"""Employment-growth outcome for the Gate-E backtest (the construct the IAI targets).

The outcome is Δ% formal-economy employment from T to T+1 by ONE activity branch —
a CHANGE, not a level, so it is not trivially circular with the IAI's
``labor_availability_T`` (an employment level). Read from the ENCFT employment
persisted under ``labor_encft``. A row with no T+1 observation is dropped (no
lookahead → never fabricated).
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.models.models import SectorVariable
from modules.sector_intel.sectors_sync import LABOR_ENCFT_DIMENSION


def employment_by_branch(db: Session) -> Dict[str, Dict[str, float]]:
    """``{branch: {period: employment}}`` from the labor_encft rows."""
    out: Dict[str, Dict[str, float]] = {}
    rows = (db.query(SectorVariable)
            .filter(SectorVariable.dimension == LABOR_ENCFT_DIMENSION,
                    SectorVariable.variable == "employment").all())
    for r in rows:
        if r.value is not None and r.period:
            out.setdefault(r.sector_code, {})[r.period] = r.value
    return out


def employment_growth(emp: Dict[str, Dict[str, float]], branch: str, year: str) -> Optional[float]:
    """Δ% employment of *branch* from *year* to *year*+1 (None without lookahead)."""
    obs = emp.get(branch, {})
    if not year.isdigit():
        return None
    base, fwd = obs.get(year), obs.get(str(int(year) + 1))
    if base is None or fwd is None or base <= 0:
        return None
    return round((fwd / base - 1.0) * 100.0, 3)


def label_panel(panel: List[Dict], emp: Dict[str, Dict[str, float]]) -> List[Dict]:
    """Attach ``emp_growth_next`` (Δ%_{T+1}) per row; drop rows without lookahead."""
    out: List[Dict] = []
    for row in panel:
        g = employment_growth(emp, row["branch"], row["period"])
        if g is None:
            continue
        out.append({**row, "emp_growth_next": g})
    return out
