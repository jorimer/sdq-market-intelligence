"""Descubridor de catálogos (Capa 3, la frontera).

A diferencia del agente (que propone desde el conocimiento del modelo, sin web), el
descubridor consulta APIs de catálogo REALES y crea sugerencias de datasets VERIFICADOS
(título, organismo, URL, formato reales). Hoy cubre el catálogo nacional CKAN de
datos.gob.do (1059 datasets, accesible con User-Agent de navegador — el 473 es solo el
bloqueo de bots). Extensible a ITU DataHub / ArcGIS DCAT.

Por cada brecha viva del readiness busca términos mapeados al eje, toma los datasets más
relevantes y los crea (``origin="catalog"``) evaluados. Idempotente por (axis, gate) y
por título (no re-descubre lo ya en el tablero). El dueño decide e integra.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from shared.source_intel.models import (
    KIND_SOURCE,
    ORIGIN_CATALOG,
    STATUS_APPROVED,
    STATUS_EVALUATED,
    STATUS_EVALUATING,
    STATUS_INTEGRATING,
    STATUS_PROPOSED,
    SourceSuggestion,
)
from shared.source_intel.service import create_suggestion, evaluate

logger = logging.getLogger("sdq.source_intel.discoverer")

_OPEN = (STATUS_PROPOSED, STATUS_EVALUATING, STATUS_EVALUATED, STATUS_APPROVED, STATUS_INTEGRATING)
_CKAN = "https://datos.gob.do/api/3/action/package_search"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Términos de búsqueda por eje (mapeo curado al lenguaje del catálogo nacional).
_AXIS_QUERIES: Dict[str, str] = {
    "telecom": "telecomunicaciones indotel",
    "energy": "energia electricidad",
    "tourism": "turismo",
    "free_zones": "zonas francas",
    "construction": "construccion vivienda",
    "agribusiness": "agropecuario agricultura",
    "trade": "comercio exterior exportaciones",
    "macro": "fiscal presupuesto cuentas nacionales",
    "esg": "medio ambiente clima",
    "banking": "banca financiero",
    "pension": "pensiones seguridad social",
}


def _ckan_search(query: str, rows: int = 3) -> List[Dict[str, Any]]:
    """Busca en el CKAN nacional (datos.gob.do) y devuelve datasets reales normalizados."""
    import httpx

    try:
        with httpx.Client(timeout=30, headers={"User-Agent": _UA, "Accept": "application/json"}) as h:
            r = h.get(_CKAN, params={"q": query, "rows": rows})
            r.raise_for_status()
            results = (r.json().get("result") or {}).get("results") or []
    except Exception as e:  # noqa: BLE001 — una búsqueda que falla no aborta el resto
        logger.warning("CKAN search '%s' falló: %s", query, e)
        return []
    out: List[Dict[str, Any]] = []
    for ds in results:
        org = (ds.get("organization") or {}).get("title") or ""
        fmts = sorted({(res.get("format") or "").upper() for res in (ds.get("resources") or []) if res.get("format")})
        url = f"https://datos.gob.do/dataset/{ds.get('name')}" if ds.get("name") else ""
        out.append({
            "title": (ds.get("title") or "").strip(),
            "org": org.strip(),
            "notes": (ds.get("notes") or "").strip(),
            "formats": fmts,
            "url": url,
        })
    return out


def _existing(db: Session) -> Tuple[Set[Tuple[Optional[str], Optional[str]]], Set[str]]:
    """``(open (axis,gate) del catálogo, títulos ya en el tablero)`` para deduplicar."""
    rows = db.query(SourceSuggestion).all()
    keys = {(r.target_axis, r.target_gate) for r in rows
            if r.origin == ORIGIN_CATALOG and r.status in _OPEN}
    titles = {(r.title or "").strip().lower() for r in rows}
    return keys, titles


def run_catalog_discovery(db: Session, set_phase=None, max_create: int = 12) -> Dict[str, Any]:
    """Recorre las brechas vivas y descubre datasets reales del catálogo nacional."""
    set_phase = set_phase or (lambda _m: None)
    from shared.products.audit import build_audit
    audit = build_audit(db)
    open_keys, seen_titles = _existing(db)
    created: List[str] = []
    hit_cap = False

    for sector in audit.get("sectors", []):
        if hit_cap:
            break
        if not sector.get("implemented"):
            continue
        axis = sector["sector_key"]
        query = _AXIS_QUERIES.get(axis)
        if not query:
            continue
        for gap in sector.get("gaps", []):
            if len(created) >= max_create:
                hit_cap = True
                break
            gate = gap.get("gate")
            if (axis, gate) in open_keys:
                continue
            set_phase(f"buscando en datos.gob.do: {axis} · {gap.get('label')}")
            datasets = _ckan_search(query, rows=3)
            open_keys.add((axis, gate))
            for ds in datasets[:2]:
                if len(created) >= max_create:
                    hit_cap = True
                    break
                title = ds["title"]
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                desc = (f"[datos.gob.do · {ds['org']}] {ds['notes'][:400]} "
                        f"Formatos: {', '.join(ds['formats']) or '—'}. {ds['url']}").strip()
                s = create_suggestion(db, kind=KIND_SOURCE, title=title[:200],
                                      description=desc[:1000], origin=ORIGIN_CATALOG,
                                      target_axis=axis, target_gate=gate)
                try:
                    evaluate(db, s["id"])
                except Exception as e:  # noqa: BLE001
                    logger.warning("auto-eval de %s falló: %s", s["id"], e)
                created.append(s["id"])

    if created:
        _notify(db, len(created))
    return {"created": len(created), "capped": hit_cap}


def _notify(db: Session, n: int) -> None:
    from shared.auth.models import User, UserRole
    from shared.notifications.service import notification_service

    admin_ids = [u.id for u in db.query(User).filter(
        User.is_active.is_(True),
        User.role.in_([UserRole.admin, UserRole.super_admin])).all()]
    title = "Inteligencia de Fuentes: datasets descubiertos"
    body = (f"El descubridor encontró {n} dataset(s) real(es) en el catálogo nacional "
            f"(datos.gob.do) para brechas del readiness. Revisar en el tablero.")
    for uid in admin_ids:
        notification_service.create(db, user_id=uid, type="info", title=title, body=body,
                                    action_url="/source-intel")
