"""Social Development — index computation, persistence and events."""
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.social_dev.events import publish_social_updated
from modules.social_dev.models.models import DevelopmentScore, SocialIndicator
from modules.social_dev.scoring.development import (
    compute_development,
    distribution_stats,
)

logger = logging.getLogger("sdq.social_dev.service")

MODEL_VERSION = "1.0"


def compute_and_persist(
    db: Session, period: str, dataset: Dict[str, Dict[str, float]]
) -> Dict[str, Any]:
    """Compute the development index for every entity in *dataset*, persist, publish.

    *dataset* is ``{entity_key: {indicator: value}}`` (regions/groups as the peer
    set, so distribution — not just the mean — is reported).
    """
    if not dataset:
        raise ValueError("Se requiere 'dataset' con al menos una entidad.")

    results: List[Dict[str, Any]] = []
    for entity_key in dataset:
        dev = compute_development(entity_key, dataset)
        row = (
            db.query(DevelopmentScore)
            .filter_by(entity_key=entity_key, period=period)
            .first()
        )
        if row is None:
            row = DevelopmentScore(entity_key=entity_key, period=period)
            db.add(row)
        row.development_score = dev["development_score"]
        row.band = dev["band"]
        row.breakdown = dev["dimensions"]
        row.model_version = MODEL_VERSION
        results.append({
            "entity_key": entity_key,
            "development_score": dev["development_score"],
            "band": dev["band"],
        })

    db.commit()
    distribution = distribution_stats([r["development_score"] for r in results])

    payload = {"period": period, "entities": results, "distribution": distribution}
    publish_social_updated(payload)
    logger.info("Social snapshot %s: %d entidades", period, len(results))
    return {
        "period": period,
        "entities": results,
        "distribution": distribution,
        "model_version": MODEL_VERSION,
    }


def get_scores(db: Session, period: Optional[str] = None) -> List[DevelopmentScore]:
    q = db.query(DevelopmentScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(DevelopmentScore.development_score.desc().nullslast()).all()


def _period_key(period: Optional[str]) -> tuple:
    """Chronological key; annual ``YYYY`` is canonical (sorts after its quarters)."""
    m = re.match(r"(\d{4})(?:-Q([1-4]))?", period or "")
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)) if m.group(2) else 5)


def get_latest(db: Session, entity_key: str) -> Optional[DevelopmentScore]:
    rows = db.query(DevelopmentScore).filter_by(entity_key=entity_key).all()
    return max(rows, key=lambda s: _period_key(s.period)) if rows else None


# IDM variable sources (Gate C): poverty by region (ONE), national series applied
# to every region (WDI health + ONE/BCRD labour: informality + income proxy),
# education by region (ONE ENHOGAR, AI-extracted), the rest declared rubric until
# sourced (financial_inclusion ← Findex/SB).
RUBRIC_VARS = ("financial_inclusion",)
EDUCATION_VARS = ("literacy_rate", "schooling_years")
HEALTH_VARS = ("life_expectancy", "child_mortality")
# National annual series (ONE/BCRD labour) applied uniformly to every region; they
# carry a declared rubric default (50) when a period lacks the real value, matching
# their prior always-rubric behaviour. income_per_capita is a declared PROXY
# (ONE hourly labour income).
NATIONAL_LIVE_VARS = ("income_per_capita", "informality_rate")
POVERTY_VAR = "poverty_rate"
# Net secondary-coverage by development region + period (ONE), like poverty: real
# regional + temporal education-access signal in the education dimension.
COVERAGE_VAR = "secondary_coverage"
HEALTH_ENTITY = "nacional"


def get_social_indicators(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Real per-entity indicators from ``sd_indicators``. Latest period per
    (entity, theme) when *period* is omitted."""
    best: Dict[tuple, tuple] = {}  # (entity, theme) -> (period, value)
    for r in db.query(SocialIndicator).all():
        if period and r.period != period:
            continue
        key = (r.entity_key, r.theme)
        cur = best.get(key)
        if cur is None or _period_key(r.period) > _period_key(cur[0]):
            best[key] = (r.period, r.value)
    out: Dict[str, Dict[str, float]] = {}
    periods = set()
    for (ent, theme), (p, val) in best.items():
        if val is not None:
            out.setdefault(ent, {})[theme] = val
            if p:
                periods.add(p)
    return {"entities": out, "period": max(periods, key=_period_key) if periods else None,
            "has_data": bool(out)}


def _poverty_periods(db: Session) -> List[str]:
    ps = {p for (p,) in db.query(SocialIndicator.period)
          .filter(SocialIndicator.theme == POVERTY_VAR).distinct() if p}
    return sorted(ps, key=_period_key)


def assemble_idm_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IDM dataset per development region for *period*: real (ONE poverty by
    region + WDI national health, applied to all regions + ONE education by region)
    + declared rubric. Single source of truth. Returns ``{period, dataset, sources,
    has_live}`` with a live|rubric provenance map per variable. *period* defaults
    to the latest."""
    from shared.data.one_client import region_catalog
    from shared.doctrine import load_doctrine_raw

    defaults = load_doctrine_raw("social").get("rubric_defaults", {})
    pov_periods = _poverty_periods(db)
    target = period or (pov_periods[-1] if pov_periods else None)
    snap = get_social_indicators(db, period=target)["entities"] if target else {}
    nat = snap.get(HEALTH_ENTITY, {})

    regions = region_catalog()
    # Education is by region from a one-off study (ENHOGAR, AI-extracted), on its
    # own period — take the latest real value per (region, var) regardless of the
    # poverty target. A variable goes live ONLY IF *every* region has it: a partial
    # fill would distort the cross-region min-max (doctrine §rubric_defaults), so
    # an incomplete extraction stays uniform rubric for all rather than half-real.
    latest = get_social_indicators(db)["entities"]
    edu_live = {
        var: all(latest.get(slug, {}).get(var) is not None for slug, _ in regions)
        for var in EDUCATION_VARS
    }

    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    for slug, _name in regions:
        merged: Dict[str, float] = {}
        smap: Dict[str, str] = {}
        for var in RUBRIC_VARS:
            merged[var] = float(defaults.get(var, 50))
            smap[var] = "rubric"
        for var in EDUCATION_VARS:  # by region (ONE ENHOGAR), live iff complete
            if edu_live[var]:
                merged[var] = float(latest[slug][var])
                smap[var] = "live"
            else:
                merged[var] = float(defaults.get(var, 50))
                smap[var] = "rubric"
        for var in HEALTH_VARS:  # national (WDI), same for all regions
            v = nat.get(var)
            if v is not None:
                merged[var] = float(v)
            smap[var] = "live" if v is not None else "rubric"
        for var in NATIONAL_LIVE_VARS:  # national (ONE labour), rubric default if absent
            v = nat.get(var)
            merged[var] = float(v) if v is not None else float(defaults.get(var, 50))
            smap[var] = "live" if v is not None else "rubric"
        pov = snap.get(slug, {}).get(POVERTY_VAR)  # by region (ONE)
        if pov is not None:
            merged[POVERTY_VAR] = float(pov)
        smap[POVERTY_VAR] = "live" if pov is not None else "rubric"
        cov = snap.get(slug, {}).get(COVERAGE_VAR)  # by region + period (ONE)
        if cov is not None:
            merged[COVERAGE_VAR] = float(cov)
        smap[COVERAGE_VAR] = "live" if cov is not None else "rubric"
        dataset[slug] = merged
        sources[slug] = smap
    return {"period": target, "dataset": dataset, "sources": sources, "has_live": bool(snap)}


def backfill_idm_scores(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Backfill the IDM for every period with real poverty data, then purge any
    score outside that set (the SIB pattern: score_all_periods + prune) — removes
    fixture/seed remnants (e.g. the old SAMPLE_REGIONS snapshot)."""
    set_phase = set_phase or (lambda _m: None)
    periods = _poverty_periods(db)
    if not periods:
        return {"scored_periods": 0, "purged": 0,
                "errors": ["sin dato social; corre one-social-sync primero"]}
    for i, p in enumerate(periods, 1):
        set_phase(f"backfill IDM {p} ({i}/{len(periods)})")
        asm = assemble_idm_dataset(db, period=p)
        compute_and_persist(db, period=p, dataset=asm["dataset"])
    set_phase("purgando scores fuera del backfill (fixture/seed)")
    keep = set(periods)
    stale = db.query(DevelopmentScore).filter(DevelopmentScore.period.notin_(keep)).all()
    purged_periods = sorted({s.period for s in stale})
    db.query(DevelopmentScore).filter(DevelopmentScore.period.notin_(keep)).delete(synchronize_session=False)
    db.commit()
    return {"scored_periods": len(periods), "periods": periods, "latest": periods[-1],
            "purged": len(stale), "purged_periods": purged_periods, "errors": []}
