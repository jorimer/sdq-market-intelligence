"""Insurance Intel — national market pulse (read side).

Builds the national pulse of the Dominican insurance market from the ingested
premium series: annual market size, growth (handling the source's 2024 = 2023
publication placeholder honestly), mix by ramo, and market structure (active
insurers). Pure reads — no AI, no mutation. The AI context (``ai_context.py``)
digests this for the narrative.
"""
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.data.sis_client import ramo_label
from modules.insurance_intel.models.models import InsuranceSeries, InsuranceSnapshot

_TOTAL = "sis.primas.total_mensual"
_RAMO = "sis.primas.ramo"
_COUNT = "sis.aseguradoras.activas_max"
_SFS_TOTAL = "sfs.afiliacion.total"
_SFS_CONTRIB = "sfs.afiliacion.contributivo"
_SFS_SUBSID = "sfs.afiliacion.subsidiado"


def _monthly(db: Session, series_code: str, dimension: Optional[str] = None,
             as_of: Optional[str] = None) -> List[Tuple[str, float]]:
    q = (
        db.query(InsuranceSeries.period, InsuranceSeries.value)
        .filter(
            InsuranceSeries.series_code == series_code,
            InsuranceSeries.entity_slug.is_(None),
            InsuranceSeries.value.isnot(None),
        )
    )
    if dimension is None:
        q = q.filter(InsuranceSeries.dimension.is_(None))
    else:
        q = q.filter(InsuranceSeries.dimension == dimension)
    if as_of:
        # Vista as-of: el pulso de un período histórico solo ve el dato hasta esa fecha
        # (los períodos "YYYY-MM" comparan lexicográficamente en orden cronológico).
        q = q.filter(InsuranceSeries.period <= as_of)
    return [(p, v) for p, v in q.order_by(InsuranceSeries.period.asc()).all()]


def _annual_totals(monthly: List[Tuple[str, float]]) -> Dict[str, float]:
    """Sum monthly RD$ into complete-year totals (only years with all 12 months)."""
    by_year: Dict[str, List[float]] = {}
    for p, v in monthly:
        by_year.setdefault(p[:4], []).append(v)
    return {y: round(sum(vs), 2) for y, vs in by_year.items() if len(vs) == 12}


def _independent_prior(annual: Dict[str, float], latest_year: str) -> Optional[str]:
    """The most recent prior year whose total differs from its own predecessor —
    i.e. skips a duplicated placeholder year (the source's 2024 == 2023 artifact)."""
    years = sorted(annual)
    idx = years.index(latest_year)
    for j in range(idx - 1, 0, -1):
        y, prev = years[j], years[j - 1]
        if abs(annual[y] - annual[prev]) > 1.0:  # a real, independent year
            return y
    return years[idx - 1] if idx >= 1 else None


def build_health_pulse(db: Session, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The national SFS health-coverage pulse (SISALRIL/CNSS): total affiliated + regime
    split + growth. None if the SFS series aren't ingested yet."""
    total = _monthly(db, _SFS_TOTAL, as_of=as_of)
    if not total:
        return None
    period, latest = total[-1]
    contrib = dict(_monthly(db, _SFS_CONTRIB, dimension="contributivo", as_of=as_of))
    subsid = dict(_monthly(db, _SFS_SUBSID, dimension="subsidiado", as_of=as_of))
    # 5-year growth (or the longest available span) of total coverage.
    prior = next((v for p, v in total if p[:4] == str(int(period[:4]) - 5)), None)
    growth = round((latest / prior - 1) * 100, 1) if prior else None
    return {
        "period": period,
        "afiliados_total": latest,
        "afiliados_contributivo": contrib.get(period),
        "afiliados_subsidiado": subsid.get(period),
        "crecimiento_5a_pct": growth,
        "source": "SISALRIL / CNSS — Seguro Familiar de Salud (dato real)",
    }


def build_market_pulse(db: Session, as_of: Optional[str] = None) -> Dict[str, Any]:
    """The national insurance-market pulse: size, growth, mix by ramo, structure.

    ``as_of`` (``"YYYY-MM"``, un período del selector) produce la vista histórica: solo
    considera series hasta esa fecha — sin él, la vista más reciente (comportamiento
    original). El selector de períodos del producto materializa un snapshot por período
    (``sis_sync._compute_snapshots``); este read reconstruye los agregados as-of."""
    monthly_total = _monthly(db, _TOTAL, as_of=as_of)
    annual = _annual_totals(monthly_total)
    snap_q = db.query(InsuranceSnapshot)
    if as_of:
        snap_q = snap_q.filter(InsuranceSnapshot.period <= as_of)
    snap = snap_q.order_by(InsuranceSnapshot.period.desc()).first()

    if not annual:
        return {
            "has_data": False,
            "period": snap.period if snap else None,
            "source": "SIS — Superintendencia de Seguros (datos.gob.do)",
        }

    latest_year = max(annual)
    total_latest = annual[latest_year]
    prior = _independent_prior(annual, latest_year)
    growth_pct = growth_years = None
    if prior and annual.get(prior):
        span = int(latest_year) - int(prior)
        ratio = total_latest / annual[prior]
        # CAGR across the (possibly multi-year) gap so a skipped placeholder year
        # doesn't inflate a single-year growth number.
        growth_pct = round((ratio ** (1 / span) - 1) * 100, 1) if span >= 1 else None
        growth_years = (prior, latest_year)

    # Mix by ramo for the latest complete year
    mix: List[Dict[str, Any]] = []
    from shared.data.sis_client import ramo_catalog
    for slug, _ in ramo_catalog():
        ann = _annual_totals(_monthly(db, _RAMO, dimension=slug, as_of=as_of))
        v = ann.get(latest_year)
        if v is not None:
            mix.append({"ramo": slug, "label": ramo_label(slug), "amount": v})
    mix.sort(key=lambda d: d["amount"], reverse=True)
    for d in mix:
        d["pct"] = round(d["amount"] / total_latest * 100, 1) if total_latest else None
    top4_pct = round(sum(d["pct"] for d in mix[:4] if d["pct"] is not None), 1) if mix else None

    counts = _monthly(db, _COUNT, as_of=as_of)
    active_insurers = int(counts[-1][1]) if counts else None

    data_caveat = None
    years_sorted = sorted(annual)
    dup_years = [
        years_sorted[i] for i in range(1, len(years_sorted))
        if abs(annual[years_sorted[i]] - annual[years_sorted[i - 1]]) <= 1.0
    ]
    if dup_years:
        data_caveat = (
            "La fuente publica un año duplicado (2024 replica exactamente a 2023, un "
            "marcador de publicación); el crecimiento se calcula como tasa compuesta "
            "entre años independientes, no interanual sobre el placeholder."
        )

    return {
        "has_data": True,
        "period": as_of or (snap.period if snap else f"{latest_year}-12"),
        "latest_year": latest_year,
        "total_premiums_rd": total_latest,
        "growth_pct": growth_pct,
        "growth_years": growth_years,
        "mix": mix,
        "top4_concentration_pct": top4_pct,
        "active_insurers": active_insurers,
        "n_ramos": len(mix),
        "annual_totals": annual,
        "data_caveat": data_caveat,
        "health_coverage": build_health_pulse(db, as_of=as_of),  # SISALRIL/SFS (None si no ingerido)
        "source": "SIS — Superintendencia de Seguros (datos.gob.do, ODbL)",
        "model_version": snap.model_version if snap else "0.1",
    }
