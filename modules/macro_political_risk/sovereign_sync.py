"""Sovereign ratings sync — scrape Wikipedia → refreshable store.

Fetches the multi-agency sovereign panel (S&P/Fitch/Moody's for DO·CR·PA·GT·JM) from
Wikipedia and persists it into the shared ``sovereign_ratings`` ``AppSetting``. The IRMP
reads the anchor (S&P) score on its next ``wdi-sync``; the banking support overlay reads it
at report time. Best-effort: a failed/empty scrape keeps the existing store (never wipes
it to the floor).

Two guards worth their lines:
  * **Preserve manual annotations.** Wikipedia carries only the last-*action* date; any
    ``affirm_date`` a human added to the store is carried forward.
  * **Report anchor changes.** The summary flags any country whose S&P (anchor) score
    moved vs the previous store — the trigger for the impact-before-deploy protocol, since
    only the anchor moves the IRMP.
"""
import logging
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.mpr.sovereign_sync")


def sovereign_ratings_sync(db: Session,
                           set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Scrape the Wikipedia sovereign panel and upsert the shared store. Returns a summary
    ``{synced, countries, agencies, anchor_changes, errors}``."""
    set_phase = set_phase or (lambda _m: None)
    from shared.contracts.sovereign_ratings import (
        ANCHOR_AGENCY, agency_score, load_sovereign_ratings, save_sovereign_ratings,
        _read_store)
    from shared.data.sovereign_ratings_client import fetch_sovereign_ratings

    # Snapshot the anchor score per country BEFORE the refresh (store or yaml floor) so we
    # can report any index-moving change afterwards.
    before = load_sovereign_ratings(db)
    before_anchor = {
        iso: agency_score(ANCHOR_AGENCY, ((c or {}).get(ANCHOR_AGENCY) or {}).get("rating"))
        for iso, c in before.items()
    }

    set_phase("consultando Wikipedia (S&P/Fitch/Moody's)")
    scraped = fetch_sovereign_ratings()
    if not scraped:
        return {"synced": 0, "countries": 0, "agencies": 0, "anchor_changes": [],
                "errors": ["Wikipedia no disponible o sin filas del panel; "
                           "se mantiene el store/piso vigente"]}

    # Carry forward any manual affirm_date annotations from the existing store.
    prev_panel = (_read_store(db) or {}).get("panel") or {}
    n_agencies = 0
    for iso, agencies in scraped.items():
        for agency, info in agencies.items():
            n_agencies += 1
            prior = (prev_panel.get(iso) or {}).get(agency) or {}
            if prior.get("affirm_date") and not info.get("affirm_date"):
                info["affirm_date"] = prior["affirm_date"]

    set_phase(f"persistiendo {len(scraped)} países ({n_agencies} calificaciones)")
    save_sovereign_ratings(db, scraped, source="wikipedia")

    # Report anchor (S&P) score changes vs before → the IRMP-moving signal.
    anchor_changes = []
    for iso, agencies in scraped.items():
        new_score = agency_score(ANCHOR_AGENCY, (agencies.get(ANCHOR_AGENCY) or {}).get("rating"))
        old_score = before_anchor.get(iso)
        if new_score != old_score:
            anchor_changes.append({
                "iso": iso,
                "old_score": old_score,
                "new_score": new_score,
                "new_rating": (agencies.get(ANCHOR_AGENCY) or {}).get("rating"),
            })
    if anchor_changes:
        logger.warning("[SOVEREIGN] cambios en el ancla S&P (mueven el IRMP): %s", anchor_changes)

    return {
        "synced": len(scraped),
        "countries": sorted(scraped),
        "agencies": n_agencies,
        "anchor_changes": anchor_changes,
        "errors": [],
    }
