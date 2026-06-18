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

# IRC variable ← ND-GAIN component (real). Transition vars are declared rubric.
_NDGAIN_MAP = {
    "climate_exposure": "exposure",
    "climate_sensitivity": "sensitivity",
    "adaptation_readiness": "readiness",
    "economic_readiness": "economic",
    "governance_quality": "governance",
    "social_readiness": "social",
}
_RUBRIC_VARS = ("fossil_dependence", "carbon_intensity")


def assemble_irc_dataset(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Full IRC dataset per country for *period*: real (ND-GAIN: physical/adaptive/
    governance) + declared rubric (transition). Returns ``{period, dataset, sources,
    reference_year, has_live}`` with a live|rubric provenance map per variable.
    *period* defaults to the ND-GAIN reference year."""
    from shared.doctrine import load_doctrine_raw

    defaults = load_doctrine_raw("esg").get("rubric_defaults", {})
    ref_year = ndgain_client.reference_year()
    target = period or ref_year
    panel = ndgain_client.panel(list(IRC_PANEL))

    dataset: Dict[str, Dict[str, float]] = {}
    sources: Dict[str, Dict[str, str]] = {}
    for iso3, comp in panel.items():
        merged: Dict[str, float] = {}
        smap: Dict[str, str] = {}
        for var, nd in _NDGAIN_MAP.items():        # ND-GAIN real
            merged[var] = float(comp[nd])
            smap[var] = "live"
        for var in _RUBRIC_VARS:                    # transition: rubric until Gate C
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
    """Assemble the IRC dataset from ND-GAIN and persist the panel snapshot."""
    set_phase = set_phase or (lambda _m: None)
    set_phase("ensamblando IRC del panel (ND-GAIN)")
    asm = assemble_irc_dataset(db)
    if not asm["dataset"]:
        return {"error": "ND-GAIN sin datos para el panel", "scored": 0, "errors": ["sin datos"]}
    set_phase(f"calculando IRC de {len(asm['dataset'])} países ({asm['period']})")
    res = compute_and_persist(db, period=asm["period"], dataset=asm["dataset"], sources=asm["sources"])
    return {"scored": len(res["countries"]), "period": asm["period"],
            "reference_year": asm["reference_year"], "countries": len(asm["dataset"]), "errors": []}


def get_scores(db: Session, period: Optional[str] = None) -> List[ESGScore]:
    q = db.query(ESGScore)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(ESGScore.esg_score.desc().nullslast()).all()  # most resilient first


def get_latest(db: Session, entity_key: str) -> Optional[ESGScore]:
    return (
        db.query(ESGScore)
        .filter_by(entity_key=entity_key)
        .order_by(ESGScore.period.desc())
        .first()
    )
