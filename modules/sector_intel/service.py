"""Sector Intel — IAI + SGPS computation, persistence and events.

For a period it computes, per sector:
  * IAI via the shared index engine (sectors normalized against each other).
  * SGPS = Histórico/Estructural/Aceleración, where Aceleración reads the live
    upstream environment (macro/irmp/trade) from the acceleration context.

Persists SectorScore rows and publishes ``sector.updated``.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

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


def _stamp_provenance(dimensions: Dict[str, Any], smap: Dict[str, str]) -> None:
    """Annotate each variable in the IAI breakdown with its ``source`` (live|rubric).

    Mutates ``dimensions`` in place. A variable absent from ``smap`` defaults to
    "rubric" (conservative: an unsourced value is declared, never assumed real).
    The readiness monitor reads this to credit cobertura by the real fraction of
    the index — honest to the data the engine actually consumed.
    """
    for dim in dimensions.values():
        for var, detail in (dim.get("variables") or {}).items():
            detail["source"] = smap.get(var, "rubric")


def compute_and_persist(
    db: Session,
    period: str,
    sector_dataset: Dict[str, Dict[str, float]],
    sgps_inputs: Optional[Dict[str, Dict[str, float]]] = None,
    country_code: str = "DO",
    sources: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Compute IAI + SGPS for every sector in *sector_dataset*, persist, publish.

    Args:
        period: snapshot label.
        sector_dataset: ``{sector_code: {variable: value}}`` (IAI peer set).
        sgps_inputs: ``{sector_code: {"historical": x, "structural": y}}``.
        country_code: country whose IRMP feeds the acceleration factor.
        sources: ``{sector_code: {variable: "live"|"rubric"}}`` from
            ``assemble_iai_dataset``. When given, each variable in the persisted
            ``iai_breakdown`` is stamped with its provenance, so the readiness
            monitor (G1) can credit cobertura honestly — the real fraction of the
            index backed by live data, not a hardcoded dimension set. Optional: the
            manual ``/snapshot`` endpoint passes none (those rows keep no source).
    """
    if not sector_dataset:
        raise ValueError("Se requiere 'sector_dataset' con al menos un sector.")

    sgps_inputs = sgps_inputs or {}
    sources = sources or {}
    # The acceleration factor is the macro environment — shared across sectors.
    acceleration = compute_acceleration(acceleration_context, country_code)

    results: List[Dict[str, Any]] = []
    for sector_code in sector_dataset:
        iai = compute_iai(sector_code, sector_dataset)
        smap = sources.get(sector_code)
        if smap:  # sin procedencia → breakdown legacy (el monitor usa su fallback)
            _stamp_provenance(iai["dimensions"], smap)
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


def get_latest_scores(db: Session) -> List[SectorScore]:
    """All sectors' scores for the most recent period (one row per sector), most
    attractive (highest IAI) first. Single query — for cross-axis snapshots."""
    rows = db.query(SectorScore).all()
    if not rows:
        return []
    latest = max(rows, key=lambda s: _period_key(s.period)).period
    return sorted(
        (s for s in rows if s.period == latest),
        key=lambda s: s.iai_score if s.iai_score is not None else -1.0,
        reverse=True,
    )


# IAI rubric variables (Gate C) — declared until sourced (negocios/talento/regulatoria).
IAI_RUBRIC_VARS = (
    "ease_of_business", "operating_cost", "labor_availability",
    "skills_index", "regulatory_quality", "regulatory_volatility",
)
# Real sector inputs from si_variables (BCRD value added).
SECTOR_LIVE_VARS = ("sector_size", "sector_growth")
# Storage dimension of the per-slug IAI inputs. Other dimensions in si_variables
# (e.g. ``labor_encft`` — branch-level ENCFT employment, the Gate-E outcome) are NOT
# index inputs and must not define the index's period grid, so reads scope to this.
SECTOR_DIMENSION = "sector"


def get_sector_variables(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Real per-sector inputs from ``si_variables`` (BCRD). Latest period per
    (sector, variable) when *period* is omitted — sources can lag differently."""
    from modules.sector_intel.models.models import SectorVariable

    q = db.query(SectorVariable).filter(SectorVariable.dimension == SECTOR_DIMENSION)
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


def _sector_periods(db: Session) -> List[str]:
    """Distinct periods present in ``si_variables``, chronologically sorted."""
    from modules.sector_intel.models.models import SectorVariable

    periods = {p for (p,) in db.query(SectorVariable.period)
               .filter(SectorVariable.dimension == SECTOR_DIMENSION).distinct() if p}
    return sorted(periods, key=_period_key)


def _load_wgi_regulatory(db: Session, target: Optional[str]) -> Optional[float]:
    """National WGI regulatory-quality (0-100) for *target*'s year, with latest-year
    fallback (WGI lags ~1 year, so the current period uses the most recent value).
    Read from the AppSetting written by ``wgi_regulatory_sync``; None if absent."""
    import json
    import re

    from modules.sector_intel.sectors_sync import WGI_REGULATORY_KEY
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == WGI_REGULATORY_KEY).first()
    if row is None or not row.value:
        return None
    try:
        series = json.loads(row.value).get("series", {})
    except (ValueError, TypeError):
        series = {}
    if not series:
        return None
    m = re.match(r"(\d{4})", target or "")
    year = m.group(1) if m else None
    if year and year in series:
        return float(series[year])
    return float(series[max(series, key=int)])  # latest available (e.g. current period)


def _load_operating_cost(db: Session) -> Dict[str, float]:
    """Per-slug ``operating_cost`` (TSS salary snapshot) from the AppSetting written
    by ``tss_salario_sync``. ``{}`` if absent → operating_cost stays declared rubric.

    Cross-sectional snapshot applied uniformly across periods (the WGI pattern): the
    TSS series only covers recent years while the IAI runs 2018-…, so a single recent
    salary photo discriminates sectors in every period.

    All-or-nothing: returned only when it covers ALL 17 slugs. A partial override
    would sink the rubric-50 sectors to the min-max floor — the exact artefact the
    doctrine forbids (sectoral.yaml). Partial coverage → ``{}`` (stay full rubric)."""
    import json

    from modules.sector_intel.sectors_sync import OPERATING_COST_KEY
    from shared.data.bcrd_sectors import sector_catalog
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == OPERATING_COST_KEY).first()
    if row is None or not row.value:
        return {}
    try:
        series = {k: float(v) for k, v in json.loads(row.value).get("series", {}).items()}
    except (ValueError, TypeError):
        return {}
    all_slugs = {slug for slug, _name in sector_catalog()}
    if not all_slugs.issubset(series):
        return {}  # partial coverage → leave every sector on declared rubric
    return {slug: series[slug] for slug in all_slugs}


def _load_labor_availability(db: Session, target: Optional[str]) -> Dict[str, float]:
    """Per-slug ``labor_availability`` (ENCFT employment) for *target*'s period.

    Reads the branch-level employment persisted under ``labor_encft`` and maps it to
    the BCRD-17 slugs via the crosswalk: a slug takes its ONE branch's employment.
    Slugs in an aggregate branch (manufactura_local/zonas_francas/mineria) share the
    branch value — a declared proxy. Per-period (real temporal signal); if *target*
    has no employment row, the latest available period is used (WGI-style fallback).

    All-or-nothing (like :func:`_load_operating_cost`): returned only when ALL 17
    slugs resolve to a branch with employment in the chosen period. Partial coverage
    → ``{}`` (stay full rubric), so a missing branch can't sink some slugs to the
    min-max floor while others carry real headcounts."""
    from modules.sector_intel.models.models import SectorVariable
    from modules.sector_intel.sectors_sync import LABOR_ENCFT_DIMENSION
    from shared.data.bcrd_sectors import sector_catalog
    from shared.data.sector_crosswalk import slug_branch

    rows = (db.query(SectorVariable)
            .filter(SectorVariable.dimension == LABOR_ENCFT_DIMENSION,
                    SectorVariable.variable == "employment").all())
    by_period: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if r.value is not None and r.period:
            by_period.setdefault(r.period, {})[r.sector_code] = r.value
    if not by_period:
        return {}
    use = target if target in by_period else max(by_period, key=_period_key)
    emp_by_branch = by_period[use]
    out: Dict[str, float] = {}
    for slug, _name in sector_catalog():
        v = emp_by_branch.get(slug_branch(slug) or "")
        if v is not None:
            out[slug] = v
    if len(out) < len(list(sector_catalog())):
        return {}  # a branch is missing this period → leave every sector on rubric
    return out


def assemble_iai_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IAI dataset per sector for *period*: declared rubric (doctrine) + real
    data (BCRD sector dim, contract-derived macro_exposure). Single source of truth
    so the persisted snapshot and the UI score the same inputs.

    The macro→sectorial contract is *current* (latest macro), so its real
    ``macro_exposure`` is used only for the latest period; for a historical
    backfill period there is no period-specific contract, so macro_exposure falls
    back to a neutral 50 (declared) — never the current contract stamped on the
    past. The sector dimension is real per period. *period* defaults to the latest.

    Returns ``{period, dataset, sources, sgps_inputs, has_live}``. ``sources``
    maps each var to ``"live"`` or ``"rubric"`` for the real-vs-rubric badge.
    """
    from shared.contracts import sector_macro_exposure
    from shared.data.bcrd_sectors import sector_catalog
    from shared.doctrine import load_doctrine_raw

    doc = load_doctrine_raw("sectoral")
    defaults = doc.get("rubric_defaults", {})
    overrides = doc.get("rubric_overrides", {})
    all_periods = _sector_periods(db)
    live_period = all_periods[-1] if all_periods else None
    target = period or live_period
    use_live_macro = target is not None and target == live_period
    live = get_sector_variables(db, period=target) if target else {"sectors": {}, "period": None, "has_data": False}
    contract = _load_macro_contract(db) if use_live_macro else {}
    factors = contract.get("factors", []) if contract else []
    # WGI regulatory quality (national, 0-100) — same for every sector (does not
    # discriminate sectors, but real instead of declared rubric).
    reg_quality = _load_wgi_regulatory(db, target)
    # operating_cost (TSS salary snapshot, per slug) + labor_availability (ENCFT
    # employment, per period) — real business/talent inputs, raise these dims out of
    # declared rubric. Both cover all 17 slugs (crosswalk), so no partial-override
    # min-max distortion. operating_cost is risk-increasing (inverted by the engine).
    op_cost = _load_operating_cost(db)
    labor = _load_labor_availability(db, target)

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
        # regulatory_quality (real, national WGI) — same for every sector.
        if reg_quality is not None:
            merged["regulatory_quality"] = reg_quality
            smap["regulatory_quality"] = "live"
        # sector dimension (real) from si_variables — overrides any rubric.
        sv = live["sectors"].get(slug, {})
        for var in SECTOR_LIVE_VARS:
            if sv.get(var) is not None:
                merged[var] = sv[var]
                smap[var] = "live"
        # operating_cost (TSS) + labor_availability (ENCFT) — real, override rubric.
        if op_cost.get(slug) is not None:
            merged["operating_cost"] = op_cost[slug]
            smap["operating_cost"] = "live"
        if labor.get(slug) is not None:
            merged["labor_availability"] = labor[slug]
            smap["labor_availability"] = "live"
        dataset[slug] = merged
        sources[slug] = smap
        sgps_inputs[slug] = {
            "historical": float(ov.get("sgps_historical", defaults.get("sgps_historical", 50))),
            "structural": float(ov.get("sgps_structural", defaults.get("sgps_structural", 50))),
        }

    return {"period": target, "dataset": dataset, "sources": sources,
            "sgps_inputs": sgps_inputs, "has_live": live["has_data"]}


def backfill_sector_scores(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Backfill the IAI/SGPS for EVERY period with real BCRD data, then purge any
    score outside that set (the SIB pattern: score_all_periods + prune).

    Removes stale ``SectorScore`` rows left by the legacy fixture-POST flow (e.g.
    a ``"2025-Q4"`` 3-sector snapshot) so the persisted index is exactly the real
    backfill — no seeded/fixture remnants. The latest period is scored last so the
    published ``sector.updated`` reflects the current snapshot.
    """
    set_phase = set_phase or (lambda _m: None)
    periods = _sector_periods(db)
    if not periods:
        return {"scored_periods": 0, "purged": 0,
                "errors": ["sin dato sectorial; corre bcrd-sectores-sync primero"]}

    for i, p in enumerate(periods, 1):
        set_phase(f"backfill IAI/SGPS {p} ({i}/{len(periods)})")
        asm = assemble_iai_dataset(db, period=p)
        compute_and_persist(db, period=p, sector_dataset=asm["dataset"],
                            sgps_inputs=asm["sgps_inputs"], sources=asm["sources"])

    set_phase("purgando scores fuera del backfill (fixture/seed)")
    keep = set(periods)
    stale = db.query(SectorScore).filter(SectorScore.period.notin_(keep)).all()
    purged_periods = sorted({s.period for s in stale})
    db.query(SectorScore).filter(SectorScore.period.notin_(keep)).delete(synchronize_session=False)
    db.commit()
    return {"scored_periods": len(periods), "periods": periods, "latest": periods[-1],
            "purged": len(stale), "purged_periods": purged_periods, "errors": []}
