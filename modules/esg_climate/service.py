"""ESG & Climate — IRC (climate resilience) computation, persistence and events.

Re-scoped 2026-06-18 to NATIONAL: the IRC is a per-country index over a Caribbean/
LatAm panel (the IRMP molde). Physical/adaptive/governance come from ND-GAIN real
data; transition (fossil/carbon) stays declared rubric until the energy/PEN source
is wired (Gate C). Single source of truth: the snapshot and the UI score the same.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.esg_climate.events import publish_esg_updated
from modules.esg_climate.models.models import ESGScore
from modules.esg_climate.scoring.exposure import compute_irc
from shared.data.ndgain_client import ndgain_client

logger = logging.getLogger("sdq.esg_climate.service")

MODEL_VERSION = "2.0"

# Caribbean + LatAm panel (ISO3 → display name). Mirrors the IRMP validation panel
# so the platform's country sets stay consistent. DR is the product focus; the
# panel is the peer set that gives the min-max meaning.
IRC_PANEL: Dict[str, str] = {
    "DOM": "República Dominicana", "HTI": "Haití", "JAM": "Jamaica",
    "TTO": "Trinidad y Tobago", "GUY": "Guyana", "SUR": "Surinam", "BLZ": "Belice",
    "CRI": "Costa Rica", "PAN": "Panamá", "GTM": "Guatemala", "SLV": "El Salvador",
    "HND": "Honduras", "NIC": "Nicaragua", "MEX": "México", "COL": "Colombia",
    "ECU": "Ecuador", "PER": "Perú", "BOL": "Bolivia", "CHL": "Chile",
    "ARG": "Argentina", "BRA": "Brasil", "PRY": "Paraguay", "URY": "Uruguay",
    "VEN": "Venezuela",
}

# Panel country → region slug (canonical, shared with the catalog i18n
# `platform.catalog.region.*`). Powers the two-step region→country selector.
IRC_REGION: Dict[str, str] = {
    "DOM": "caribe", "HTI": "caribe", "JAM": "caribe", "TTO": "caribe",
    "BLZ": "centroamerica", "CRI": "centroamerica", "PAN": "centroamerica",
    "GTM": "centroamerica", "SLV": "centroamerica", "HND": "centroamerica",
    "NIC": "centroamerica", "MEX": "norteamerica",
    "GUY": "sudamerica", "SUR": "sudamerica", "COL": "sudamerica", "ECU": "sudamerica",
    "PER": "sudamerica", "BOL": "sudamerica", "CHL": "sudamerica", "ARG": "sudamerica",
    "BRA": "sudamerica", "PRY": "sudamerica", "URY": "sudamerica", "VEN": "sudamerica",
}

# IRC variable ← ND-GAIN component (real). Transition vars are declared rubric;
# hurricane_exposure (physical) comes from HURDAT2 (Gate B), ND-GAIN as fallback.
_NDGAIN_MAP = {
    "climate_sensitivity": "sensitivity",
    "adaptation_readiness": "readiness",
    "economic_readiness": "economic",
    "governance_quality": "governance",
    "social_readiness": "social",
}
_RUBRIC_VARS = ("fossil_dependence", "carbon_intensity")


def assemble_irc_dataset(
    db: Session, period: Optional[str] = None,
    hurricane_exp: Optional[Dict[str, float]] = None,
    transition: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Full IRC dataset per country for *period*: real (ND-GAIN: sensitivity +
    adaptive + governance; HURDAT2: hurricane exposure) + declared rubric
    (transition). Returns ``{period, dataset, sources, reference_year, has_live}``
    with a live|rubric provenance map per variable. *hurricane_exp* (HURDAT2, by
    iso3) feeds physical exposure; if absent, falls back to ND-GAIN exposure.
    *period* defaults to the ND-GAIN reference year."""
    from shared.doctrine import load_doctrine_raw

    defaults = load_doctrine_raw("esg").get("rubric_defaults", {})
    ref_year = ndgain_client.reference_year()
    target = period or ref_year
    panel = ndgain_client.panel(list(IRC_PANEL))

    # Transition goes live ONLY IF every panel country has both metrics — a partial
    # fill would distort the cross-country min-max (the IDM education lesson). Ember
    # covers the whole panel, so in practice this passes.
    transition_live = bool(transition) and all(
        iso in transition and all(v in transition[iso] for v in _RUBRIC_VARS)
        for iso in panel
    )

    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    for iso3, comp in panel.items():
        merged: Dict[str, float] = {}
        smap: Dict[str, str] = {}
        for var, nd in _NDGAIN_MAP.items():        # ND-GAIN real
            merged[var] = float(comp[nd])
            smap[var] = "live"
        # Physical exposure: HURDAT2 hurricane exposure (real), ND-GAIN as fallback.
        if hurricane_exp is not None and iso3 in hurricane_exp:
            merged["hurricane_exposure"] = float(hurricane_exp[iso3])
        else:
            merged["hurricane_exposure"] = float(comp["exposure"])
        smap["hurricane_exposure"] = "live"
        # Transition: Ember real if the panel is complete, else declared rubric.
        for var in _RUBRIC_VARS:
            if transition_live:
                merged[var] = float(transition[iso3][var])
                smap[var] = "live"
            else:
                merged[var] = float(defaults.get(var, 0.5))
                smap[var] = "rubric"
        dataset[iso3] = merged
        sources[iso3] = smap
    return {"period": target, "dataset": dataset, "sources": sources,
            "reference_year": ref_year, "has_live": bool(dataset)}


def compute_and_persist(
    db: Session, period: str, dataset: Dict[str, Dict[str, float]],
    sources: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Compute the IRC for every country in *dataset*, persist, publish."""
    if not dataset:
        raise ValueError("Se requiere 'dataset' con al menos un país.")

    results: List[Dict[str, Any]] = []
    for entity_key in dataset:
        irc = compute_irc(entity_key, dataset)
        row = db.query(ESGScore).filter_by(entity_key=entity_key, period=period).first()
        if row is None:
            row = ESGScore(entity_key=entity_key, period=period)
            db.add(row)
        row.esg_score = irc["esg_score"]
        row.band = irc["band"]
        row.breakdown = {"dimensions": irc["dimensions"],
                         "sources": (sources or {}).get(entity_key, {})}
        row.model_version = MODEL_VERSION
        results.append({"entity_key": entity_key, "esg_score": irc["esg_score"], "band": irc["band"]})

    db.commit()
    payload = {"period": period, "countries": results}
    publish_esg_updated(payload)
    logger.info("IRC snapshot %s: %d países", period, len(results))
    return {"period": period, "countries": results, "model_version": MODEL_VERSION}


def esg_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Assemble the IRC dataset (ND-GAIN + HURDAT2 hurricane exposure) and persist
    the panel snapshot. HURDAT2 is best-effort: on failure, physical exposure falls
    back to ND-GAIN (the IRC still computes on real data)."""
    set_phase = set_phase or (lambda _m: None)

    hurricane_exp: Optional[Dict[str, float]] = None
    hurdat2_year = None
    set_phase("descargando exposición a huracanes (HURDAT2/NOAA)")
    try:
        from shared.data.hurdat2_client import hurdat2_client
        hurricane_exp, hurdat2_year = hurdat2_client.fetch_exposure(list(IRC_PANEL))
    except Exception as e:  # noqa: BLE001 — Gate B best-effort; fallback to ND-GAIN
        logger.warning("HURDAT2 no disponible, físico cae a ND-GAIN: %s", e)

    transition: Optional[Dict[str, Dict[str, float]]] = None
    set_phase("descargando transición eléctrica (Ember: fósil + carbono)")
    try:
        from shared.data.ember_client import ember_client
        transition = ember_client.fetch_transition(list(IRC_PANEL))
    except Exception as e:  # noqa: BLE001 — Gate C best-effort; fallback to rubric
        logger.warning("Ember no disponible, transición cae a rúbrica: %s", e)

    set_phase("ensamblando IRC del panel (ND-GAIN + HURDAT2 + Ember)")
    asm = assemble_irc_dataset(db, hurricane_exp=hurricane_exp, transition=transition)
    if not asm["dataset"]:
        return {"error": "ND-GAIN sin datos para el panel", "scored": 0, "errors": ["sin datos"]}
    transition_live = asm["sources"].get("DOM", {}).get("fossil_dependence") == "live"
    set_phase(f"calculando IRC de {len(asm['dataset'])} países ({asm['period']})")
    res = compute_and_persist(db, period=asm["period"], dataset=asm["dataset"], sources=asm["sources"])
    return {"scored": len(res["countries"]), "period": asm["period"],
            "reference_year": asm["reference_year"],
            "hurricane_source": "HURDAT2" if hurricane_exp else "ND-GAIN (fallback)",
            "hurdat2_year": hurdat2_year,
            "transition_source": "Ember" if transition_live else "rúbrica (fallback)",
            "countries": len(asm["dataset"]), "errors": []}


def get_scores(db: Session, period: Optional[str] = None) -> List[ESGScore]:
    q = db.query(ESGScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(ESGScore.esg_score.desc().nullslast()).all()  # most resilient first


def get_scored_entities(db: Session) -> List[str]:
    """Distinct country ISO3 codes with at least one persisted IRC score, in panel
    order. The catalog offers only countries that actually produce a report (never an
    option that would 422)."""
    keys = {k for (k,) in db.query(ESGScore.entity_key).distinct().all()}
    return [iso for iso in IRC_PANEL if iso in keys]


def get_for_entity_period(db: Session, entity_key: str, period: str) -> Optional[ESGScore]:
    """IRC for *entity_key* at *period*, or the entity's most recent if absent (the
    panel may lag the global period). Per-country analog of ``get_latest``."""
    if period:
        hit = db.query(ESGScore).filter_by(entity_key=entity_key, period=period).first()
        if hit is not None:
            return hit
    return get_latest(db, entity_key)


def get_latest(db: Session, entity_key: str) -> Optional[ESGScore]:
    return (
        db.query(ESGScore)
        .filter_by(entity_key=entity_key)
        .order_by(ESGScore.period.desc())
        .first()
    )


# ─── Superficie para la Data API (docs/SPEC_API_DATOS_PROPIETARIOS.md F2) ──


def describe_irc_for_api(db: Session) -> Dict[str, Any]:
    """Descriptor del IRC para el manifiesto de la Data API."""
    subjects = get_scored_entities(db)
    latest = (
        db.query(ESGScore).order_by(ESGScore.period.desc()).first()
    )
    return {
        "code": "irc",
        "label": "Índice de Resiliencia Climática (IRC)",
        "subject_kind": "country",
        "direction": "mayor score = mayor resiliencia / menor riesgo climático",
        "scale": "0-100",
        "method_version": str(latest.model_version) if latest else None,
        "subjects": tuple(subjects),
        "period_latest": str(latest.period) if latest else None,
        "n_obs": int(db.query(ESGScore).count()),
    }


def irc_observations_for_api(
    db: Session,
    *,
    subject: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Observaciones del IRC con desglose dimensional numérico (nunca narrativa).

    Sin ``subject`` = panel del último período; con ``subject`` = trayectoria del país.
    """
    q = db.query(ESGScore)
    if subject:
        q = q.filter(ESGScore.entity_key == subject.upper())
    if start:
        q = q.filter(ESGScore.period >= start)
    if end:
        q = q.filter(ESGScore.period <= end)
    rows = q.order_by(ESGScore.period.desc()).all()

    if not subject:
        seen: set = set()
        rows = [r for r in rows if not (r.entity_key in seen or seen.add(r.entity_key))]
    if limit is not None and limit > 0:
        rows = rows[: int(limit)]

    out: List[Dict[str, Any]] = []
    for r in rows:
        dims = ((r.breakdown or {}).get("dimensions") or None)
        out.append({
            "subject": str(r.entity_key),
            "period": str(r.period),
            "score": float(r.esg_score) if r.esg_score is not None else None,
            "band": r.band,
            "dimensions": dims,
            "model_version": str(r.model_version) if r.model_version else None,
            "reason": None if r.esg_score is not None else "sin score computado",
        })
    return out
