"""Sector Intel — IAI + SGPS computation, persistence and events.

For a period it computes, per sector:
  * IAI via the shared index engine (sectors normalized against each other).
  * SGPS = Histórico/Estructural/Aceleración, where Aceleración reads the live
    upstream environment (macro/irmp/trade) from the acceleration context.

Persists SectorScore rows and publishes ``sector.updated``.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.sector_intel.events import (
    acceleration_context,
    publish_sector_updated,
)
from modules.sector_intel.models.models import Sector, SectorScore
from modules.sector_intel.scoring.acceleration import compute_acceleration
from modules.sector_intel.scoring.iai import compute_iai
from modules.sector_intel.scoring.sgps import compute_sgps

logger = logging.getLogger("sdq.sector_intel.service")

MODEL_VERSION = "1.0"

# Sector catalog (decision 2026-06-16, owner): the full-economy leaf partition
# from the BCRD national accounts (~17 sectors summing to total Value Added),
# replacing the original 3 anchors. Single source of truth lives in
# ``shared.data.bcrd_sectors`` (the connector that populates them with real data).
from shared.data.bcrd_sectors import sector_catalog

ANCHOR_SECTORS = sector_catalog()


def seed_sectors(db: Session) -> int:
    """Ensure the sector catalog exists.  Returns how many were created."""
    created = 0
    for code, name in ANCHOR_SECTORS:
        if db.query(Sector).filter_by(code=code).first() is None:
            db.add(Sector(code=code, name=name))
            created += 1
    db.commit()
    return created


def compute_and_persist(
    db: Session,
    period: str,
    sector_dataset: Dict[str, Dict[str, float]],
    sgps_inputs: Optional[Dict[str, Dict[str, float]]] = None,
    country_code: str = "DO",
) -> Dict[str, Any]:
    """Compute IAI + SGPS for every sector in *sector_dataset*, persist, publish.

    Args:
        period: snapshot label.
        sector_dataset: ``{sector_code: {variable: value}}`` (IAI peer set).
        sgps_inputs: ``{sector_code: {"historical": x, "structural": y}}``.
        country_code: country whose IRMP feeds the acceleration factor.
    """
    if not sector_dataset:
        raise ValueError("Se requiere 'sector_dataset' con al menos un sector.")

    sgps_inputs = sgps_inputs or {}
    # The acceleration factor is the macro environment — shared across sectors.
    acceleration = compute_acceleration(acceleration_context, country_code)

    results: List[Dict[str, Any]] = []
    for sector_code in sector_dataset:
        iai = compute_iai(sector_code, sector_dataset)
        si = sgps_inputs.get(sector_code, {})
        sgps = compute_sgps(
            historical=si.get("historical"),
            structural=si.get("structural"),
            acceleration=acceleration["acceleration"],
        )

        row = (
            db.query(SectorScore)
            .filter_by(sector_code=sector_code, period=period)
            .first()
        )
        if row is None:
            row = SectorScore(sector_code=sector_code, period=period)
            db.add(row)
        row.iai_score = iai["iai_score"]
        row.iai_band = iai["band"]
        row.sgps_score = sgps["sgps_score"]
        row.iai_breakdown = iai["dimensions"]
        row.sgps_breakdown = {**sgps, "acceleration_detail": acceleration}
        row.model_version = MODEL_VERSION

        results.append({
            "sector_code": sector_code,
            "iai_score": iai["iai_score"],
            "iai_band": iai["band"],
            "sgps_score": sgps["sgps_score"],
        })

    db.commit()

    payload = {"period": period, "sectors": results, "acceleration": acceleration["acceleration"]}
    publish_sector_updated(payload)
    logger.info("Sector snapshot %s: %d sectores", period, len(results))
    return {
        "period": period,
        "country_code": country_code,
        "acceleration": acceleration,
        "sectors": results,
        "model_version": MODEL_VERSION,
    }


def get_sectors(db: Session) -> List[Sector]:
    return db.query(Sector).order_by(Sector.code).all()


def _period_key(period: Optional[str]) -> tuple:
    """Chronological sort key for a period label, robust to mixed formats.

    The BCRD value-added connector emits annual ``YYYY`` — the canonical full-year
    figure, which must sort *after* any quarter of that year (sentinel ``5`` >
    ``Q4``). So the annual snapshot wins over stale quarterly rows left by the
    legacy fixture-POST flow (``"2025"`` beats ``"2025-Q4"``), and lexical ordering
    — which would mis-rank these — is avoided (the macro_monitor period lesson)."""
    import re

    m = re.match(r"(\d{4})(?:-Q([1-4]))?", period or "")
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 5)


def get_latest(db: Session, sector_code: str) -> Optional[SectorScore]:
    rows = db.query(SectorScore).filter_by(sector_code=sector_code).all()
    return max(rows, key=lambda s: _period_key(s.period)) if rows else None


# IAI rubric variables (Gate C) — declared until sourced (negocios/talento/regulatoria).
IAI_RUBRIC_VARS = (
    "ease_of_business", "operating_cost", "labor_availability",
    "skills_index", "regulatory_quality", "regulatory_volatility",
)
# Real sector inputs from si_variables (BCRD value added).
SECTOR_LIVE_VARS = ("sector_size", "sector_growth")


def get_sector_variables(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Real per-sector inputs from ``si_variables`` (BCRD). Latest period per
    (sector, variable) when *period* is omitted — sources can lag differently."""
    from modules.sector_intel.models.models import SectorVariable

    q = db.query(SectorVariable)
    if period:
        q = q.filter(SectorVariable.period == period)
    best: Dict[tuple, tuple] = {}  # (sector, var) -> (period, value)
    for r in q.all():
        key = (r.sector_code, r.variable)
        cur = best.get(key)
        if cur is None or _period_key(r.period) > _period_key(cur[0]):
            best[key] = (r.period, r.value)
    sectors: Dict[str, Dict[str, float]] = {}
    periods = set()
    for (sc, var), (p, val) in best.items():
        if val is not None:
            sectors.setdefault(sc, {})[var] = val
            if p:
                periods.add(p)
    return {"sectors": sectors,
            "period": max(periods, key=_period_key) if periods else None,
            "has_data": bool(sectors)}


def _load_macro_contract(db: Session) -> Dict[str, Any]:
    """Read the latest macro→sectorial contract from the shared AppSetting
    (written by macro_monitor). Empty dict if none yet — macro_exposure then
    falls back to a neutral 50 (declared), never fabricated."""
    import json

    from shared.contracts import APP_SETTING_KEY
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    if row is None or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return {}


def assemble_iai_dataset(db: Session) -> Dict[str, Any]:
    """Full IAI dataset per sector: declared rubric (doctrine) + real data
    (BCRD sector dim, contract-derived macro_exposure). Single source of truth so
    the persisted snapshot and the UI score the same inputs.

    Returns ``{period, dataset, sources, sgps_inputs, has_live}``. ``sources``
    maps each var to ``"live"`` or ``"rubric"`` for the real-vs-rubric badge.
    """
    from shared.contracts import sector_macro_exposure
    from shared.data.bcrd_sectors import sector_catalog
    from shared.doctrine import load_doctrine_raw

    doc = load_doctrine_raw("sectoral")
    defaults = doc.get("rubric_defaults", {})
    overrides = doc.get("rubric_overrides", {})
    live = get_sector_variables(db)
    contract = _load_macro_contract(db)
    factors = contract.get("factors", []) if contract else []

    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    sgps_inputs: Dict[str, Dict[str, float]] = {}

    for slug, _name in sector_catalog():
        ov = overrides.get(slug, {})
        merged: Dict[str, float] = {}
        smap: Dict[str, str] = {}
        # Rubric (declared) for the not-yet-sourced dimensions.
        for var in IAI_RUBRIC_VARS:
            merged[var] = float(ov.get(var, defaults.get(var, 50)))
            smap[var] = "rubric"
        # macro_exposure (real) — derived per-sector from the macro contract.
        merged["macro_exposure"] = sector_macro_exposure(factors, slug)
        smap["macro_exposure"] = "live" if factors else "rubric"
        # sector dimension (real) from si_variables — overrides any rubric.
        sv = live["sectors"].get(slug, {})
        for var in SECTOR_LIVE_VARS:
            if sv.get(var) is not None:
                merged[var] = sv[var]
                smap[var] = "live"
        dataset[slug] = merged
        sources[slug] = smap
        sgps_inputs[slug] = {
            "historical": float(ov.get("sgps_historical", defaults.get("sgps_historical", 50))),
            "structural": float(ov.get("sgps_structural", defaults.get("sgps_structural", 50))),
        }

    return {"period": live["period"], "dataset": dataset, "sources": sources,
            "sgps_inputs": sgps_inputs, "has_live": live["has_data"]}
