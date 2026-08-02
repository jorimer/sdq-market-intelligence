"""Sovereign credit ratings — refreshable multi-agency store + combination policy.

Two consumers read a country's sovereign rating: the **IRMP** (``sovereign_rating_score``,
the *external* dimension — :func:`shared.data.wdi_client.declared_sovereign_records`) and
the **banking support overlay** (Fase 6a *techo soberano* —
:func:`modules.banking_score.scoring.support.sovereign_anchor`). Historically the ratings
lived hardcoded in ``regulatory.yaml`` (S&P only) and rotted silently: DR's ``as_of`` sat
at 2022 long after newer affirmations. This module moves them to a **refreshable store**
(``AppSetting``, written by ``sovereign-ratings-sync`` from Wikipedia) with the yaml as the
declared **floor**, and centralizes the multi-agency read so both consumers share one
source. Mirrors the ``macro_sector`` contract pattern (AppSetting + fallback, no producer
import).

Design decisions (owner, 2026-07-01):
  * **Multi-agency, S&P-anchored.** The store carries S&P + Fitch + Moody's per country,
    but the combined ``sovereign_rating_score`` that feeds the index is **S&P's** (política
    "S&P manda"): Fitch/Moody's travel as CONTEXT for narrative — they do *not* move the
    index. Switching the anchor is the one-constant :data:`ANCHOR_AGENCY` change, gated by
    the same impact-before-deploy protocol that governs any score mutation.
  * **Date = last action, plus an optional affirmation note.** Wikipedia carries the last
    rating ACTION date (e.g. DR S&P 2022-12-19). A later *affirmation* at the same grade is
    not on Wikipedia; it stays an optional manual ``affirm_date`` annotation.
  * **Never fabricate.** Missing agency → absent. No store / no db → yaml floor.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

# AppSetting key under which ``sovereign-ratings-sync`` persists the scraped panel.
APP_SETTING_KEY = "sovereign_ratings"

# Combination policy (owner 2026-07-01): S&P is the anchor whose rating feeds the index.
ANCHOR_AGENCY = "sp"

# Months since the last verified touch (agency action OR manual affirmation) before the
# freshness audit PROPOSES re-verification. Lives here so the audit and the sovereign
# panel (API/UI) share one criterion. Agencies usually act/affirm within ~2 years.
STALE_AFTER_MONTHS = 24

AGENCY_NAMES: Dict[str, str] = {"sp": "S&P", "fitch": "Fitch", "moodys": "Moody's"}
# Display order for the context panel (anchor first).
AGENCY_ORDER = ("sp", "fitch", "moodys")

# Moody's notation → S&P-equivalent notch, so a Moody's grade maps onto the declared
# ``rating_scale`` (S&P notation) for the CONTEXT panel. Standard agency equivalence.
MOODYS_TO_SP: Dict[str, str] = {
    "Aaa": "AAA",
    "Aa1": "AA+", "Aa2": "AA", "Aa3": "AA-",
    "A1": "A+", "A2": "A", "A3": "A-",
    "Baa1": "BBB+", "Baa2": "BBB", "Baa3": "BBB-",
    "Ba1": "BB+", "Ba2": "BB", "Ba3": "BB-",
    "B1": "B+", "B2": "B", "B3": "B-",
    "Caa1": "CCC+", "Caa2": "CCC", "Caa3": "CCC-",
    "Ca": "CC", "C": "D",
}


def _rating_scale() -> Dict[str, Any]:
    """The declared S&P notch → 0-100 scale from doctrine (``regulatory.yaml``)."""
    from shared.doctrine.loader import load_doctrine_raw

    return load_doctrine_raw("regulatory").get("rating_scale") or {}


def agency_score(agency: str, rating: Optional[str]) -> Optional[float]:
    """0-100 for an agency's *rating* via the declared S&P scale. Moody's grades are mapped
    to their S&P equivalent first. Unknown grade → None (never guessed)."""
    if not rating:
        return None
    sp_notation = MOODYS_TO_SP.get(rating, rating) if agency == "moodys" else rating
    score = _rating_scale().get(sp_notation)
    return float(score) if score is not None else None


def _yaml_floor() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Declared floor from ``regulatory.yaml`` ``sovereign_ratings`` (S&P only, one agency
    per country). Used when no refreshable store exists yet (fresh deploy / offline)."""
    from shared.doctrine.loader import load_doctrine_raw

    ratings = load_doctrine_raw("regulatory").get("sovereign_ratings") or {}
    floor: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for iso, info in ratings.items():
        if not isinstance(info, dict):
            continue
        agency = (info.get("agency") or "S&P").strip().lower()
        slug = "sp" if agency in ("s&p", "sp", "standard & poor's") else agency
        floor[iso] = {slug: {
            "rating": info.get("rating"),
            "outlook": None,
            "action_date": info.get("as_of"),
            "affirm_date": None,
            "source_url": None,
            "source": "regulatory.yaml (floor)",
        }}
    return floor


def _read_store(db) -> Dict[str, Any]:
    """Raw envelope from the AppSetting, or ``{}`` if none/invalid/unavailable. Defensive by
    design: a missing table (fresh DB pre-migration) or any query error must fall back to the
    declared floor, never crash a report or a sync."""
    from shared.settings.models import AppSetting

    try:
        row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    except Exception:  # noqa: BLE001 — sin store accesible → piso declarado
        db.rollback()
        return {}
    if row is None or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return {}


def load_sovereign_ratings(db=None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The sovereign panel ``{iso: {agency: {rating, outlook, action_date, affirm_date,
    source_url, …}}}``. Prefers the refreshable store (``AppSetting``, when *db* given);
    the yaml floor fills any country the store lacks. Never fabricates."""
    floor = _yaml_floor()
    if db is None:
        return floor
    stored = (_read_store(db) or {}).get("panel") or {}
    if not stored:
        return floor
    # Per-country: the store is authoritative where present; the floor fills the rest.
    panel = dict(floor)
    for iso, agencies in stored.items():
        if isinstance(agencies, dict) and agencies:
            panel[iso] = agencies
    return panel


def save_sovereign_ratings(db, panel: Dict[str, Any], source: str = "wikipedia",
                           fetched_at: Optional[str] = None) -> None:
    """Persist the scraped *panel* into the shared ``AppSetting`` (envelope with source +
    fetch date). Idempotent upsert."""
    from shared.settings.models import AppSetting

    envelope = {
        "panel": panel,
        "source": source,
        "fetched_at": fetched_at or date.today().isoformat(),
    }
    payload = json.dumps(envelope, ensure_ascii=False)
    row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    if row:
        row.value = payload
        row.is_secret = False
    else:
        db.add(AppSetting(key=APP_SETTING_KEY, value=payload, is_secret=False))
    db.commit()


def _agencies_detail(country: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-agency context rows (anchor first): rating + its 0-100 on the declared scale +
    outlook + action date. The CONTEXT panel that surfaces multi-agency divergence."""
    detail: List[Dict[str, Any]] = []
    for agency in AGENCY_ORDER:
        info = country.get(agency)
        if not info or not info.get("rating"):
            continue
        detail.append({
            "agency": agency,
            "name": AGENCY_NAMES.get(agency, agency),
            "rating": info.get("rating"),
            "outlook": info.get("outlook"),
            "action_date": info.get("action_date"),
            "score": agency_score(agency, info.get("rating")),
            "is_anchor": agency == ANCHOR_AGENCY,
        })
    return detail


def combined_anchor(iso: str, db=None) -> Dict[str, Any]:
    """The sovereign anchor for *iso* under the combination policy (S&P manda): the anchor
    agency's rating/score/date drive the index; the other agencies ride along as context.

    Returns keys back-compatible with the old ``sovereign_anchor()`` (``rating``,
    ``agency``, ``as_of``, ``score``) plus ``outlook``, ``affirm_date`` and an ``agencies``
    context list. Missing anchor → those keys are None (declared, not fabricated)."""
    country = load_sovereign_ratings(db).get(iso) or {}
    anchor = country.get(ANCHOR_AGENCY) or {}
    rating = anchor.get("rating")
    return {
        "rating": rating,
        "agency": AGENCY_NAMES.get(ANCHOR_AGENCY, ANCHOR_AGENCY),
        "as_of": anchor.get("action_date"),
        "affirm_date": anchor.get("affirm_date"),
        "outlook": anchor.get("outlook"),
        "score": agency_score(ANCHOR_AGENCY, rating),
        "agencies": _agencies_detail(country),
    }


def annotate_affirmation(db, iso: str, affirm_date: str,
                         agency: str = ANCHOR_AGENCY) -> bool:
    """Anota (o corrige) la fecha de AFIRMACIÓN manual de un rating en el store — la acción
    humana que pide la auditoría de frescura ("verificar que siga vigente y anotar"). Escribe
    ``affirm_date`` en ``panel[iso][agency]`` preservando el resto del sobre (source,
    fetched_at); el sync la arrastra hacia adelante en cada refresco. Devuelve False si no
    hay store o el país/agencia no está en el panel (la auditoría solo vigila el store, así
    que no hay nada que silenciar): nunca fabrica una entrada.

    ``affirm_date`` debe ser ISO ``YYYY-MM-DD``; inválida → ValueError (el borde del API la
    traduce a 422 en español)."""
    date.fromisoformat(affirm_date)  # valida; ValueError si viene mal
    from shared.settings.models import AppSetting

    envelope = _read_store(db)
    info = ((envelope.get("panel") or {}).get(iso) or {}).get(agency)
    if not info:
        return False
    info["affirm_date"] = affirm_date
    row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    row.value = json.dumps(envelope, ensure_ascii=False)
    db.commit()
    return True


def _months_between(iso_date: str, today: date) -> Optional[int]:
    """Whole months between an ISO ``YYYY-MM-DD`` and *today*, or None if unparseable."""
    try:
        d = date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return None
    return (today.year - d.year) * 12 + (today.month - d.month)


def overdue_ratings(db, max_age_months: int, today: Optional[date] = None,
                    agency: str = ANCHOR_AGENCY) -> List[Dict[str, Any]]:
    """Store-backed panel entries whose *anchor* rating action is older than
    *max_age_months* — the freshness signal the audit turns into a human PROPOSAL (verify
    the value is current; the module never overwrites a rating on its own). Sorted
    oldest-first.

    Intentionally reads the REFRESHABLE STORE only, not the yaml floor: the floor is the
    PR-governed declared baseline the owner already maintains, so proposing to re-verify it
    would be noise. Once ``sovereign-ratings-sync`` populates the store with real scraped
    action dates, this watches those for staleness."""
    today = today or date.today()
    panel = (_read_store(db) or {}).get("panel") or {}
    stale: List[Dict[str, Any]] = []
    for iso, country in panel.items():
        info = (country or {}).get(agency) or {}
        action = info.get("action_date")
        # La frescura se mide desde el último toque HUMANO-verificado: la acción de la
        # agencia o una afirmación anotada a mano, lo más reciente. Sin esto, anotar la
        # afirmación (lo que la propuesta pide hacer) no silenciaba la propuesta.
        touches = [d for d in (action, info.get("affirm_date")) if d]
        ages = [a for a in (_months_between(d, today) for d in touches) if a is not None]
        age = min(ages) if ages else None
        if age is not None and age > max_age_months:
            stale.append({"iso": iso, "agency": agency, "rating": info.get("rating"),
                          "action_date": action, "affirm_date": info.get("affirm_date"),
                          "age_months": age})
    stale.sort(key=lambda r: r["age_months"], reverse=True)
    return stale
