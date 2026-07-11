"""Completitud de fuentes del BCRD — propone hermanos sin cablear del catálogo.

El catálogo del CDN (``bcrd_excel/catalog_data.json``) es el inventario DESCUBIERTO
de los Excel del BCRD (~708 archivos). Los conectores cablean solo algunos por nombre
fijo. Un archivo puede estar en el catálogo y no cablearse — exactamente lo que pasó con
``pib_origen_retro_2018_2007.xlsx`` (estaba inventariado; el conector sectorial usaba solo
``pib_origen_2018.xlsx``). Este audit cierra ese hueco: por cada familia de archivo que un
conector YA cablea, busca en el catálogo hermanos NO cableados que sean plausiblemente
mejores —variante con más historia (retro/empalme) o base más nueva— y los sube al tablero
de Inteligencia de Fuentes como sugerencias para que el dueño decida (doctrina: el sistema
propone, el dueño dispone). Verifica que el hermano resuelva (HEAD 200) para no proponer
archivos muertos (lección: el CDN del BCRD renombra sin aviso).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from shared.source_intel.models import (
    KIND_SOURCE,
    ORIGIN_CATALOG,
    SourceSuggestion,
)
from shared.source_intel.service import create_suggestion

logger = logging.getLogger("sdq.source_intel.bcrd_completeness")

_YEAR = re.compile(r"(?:19|20)\d{2}")
# Marcadores de "variante de historia" (la clase valiosa: serie empalmada/retropolada).
_VARIANT_MARKERS = ("retro", "retropol", "empalme", "empalmad", "referencial", "historic")
_STRIP_TOKENS = _VARIANT_MARKERS + ("base", "serie")


def _family_key(filename: str) -> str:
    """Clave de familia de un archivo: nombre sin extensión, años, marcadores de variante
    ni tokens de base → el tronco estable. ``pib_origen_2018.xlsx`` y
    ``pib_origen_retro_2018_2007.xlsx`` comparten familia ``pib origen``."""
    stem = re.sub(r"\.[a-z0-9]+$", "", filename.lower())
    stem = _YEAR.sub(" ", stem)
    for tok in _STRIP_TOKENS:
        stem = stem.replace(tok, " ")
    stem = re.sub(r"[^a-z]+", " ", stem)
    return " ".join(stem.split())


def _has_variant_marker(filename: str) -> bool:
    low = filename.lower()
    return any(m in low for m in _VARIANT_MARKERS)


def _max_year(filename: str) -> int:
    years = [int(y) for y in _YEAR.findall(filename)]
    return max(years) if years else 0


def _wired_bcrd_files() -> Dict[str, str]:
    """``{filename_lower: filename}`` de los Excel del BCRD que los conectores CABLEAN
    (nombre fijo): el sectorial (PIB por origen vigente + retropolado) y el set canónico
    del ETL histórico. Es lo que ya usamos — la base para buscar hermanos."""
    from shared.data.bcrd_excel.canonical import registry
    from shared.data.bcrd_sectors import PIB_ORIGEN_RETRO_URL, PIB_ORIGEN_URL

    files: Dict[str, str] = {}
    for url in (PIB_ORIGEN_URL, PIB_ORIGEN_RETRO_URL):
        name = url.split("/")[-1].split("?")[0]
        files[name.lower()] = name
    for cs in registry():
        if cs.source_file:
            files[cs.source_file.lower()] = cs.source_file
    return files


def _head_ok(url: str) -> bool:  # pragma: no cover - network I/O
    import httpx

    try:
        resp = httpx.head(url, timeout=20, follow_redirects=True)
        return resp.status_code == 200
    except Exception as e:  # noqa: BLE001 — un hermano no verificable simplemente no se propone
        logger.warning("[bcrd_completeness] HEAD falló para %s: %s", url, e)
        return False


def find_uncabled_siblings(check_live: bool = True) -> List[Dict[str, Any]]:
    """Hermanos del catálogo NO cableados que son candidatos (misma familia que un archivo
    cableado + marcador de variante O año más nuevo que el máximo cableado de la familia).
    ``[{filename, url, family, wired_example, reason}]``."""
    from shared.data.bcrd_excel.catalog import load_catalog

    wired = _wired_bcrd_files()
    wired_lower = set(wired)
    # Familia → (máximo año cableado, ejemplo de archivo cableado).
    fam_wired: Dict[str, Dict[str, Any]] = {}
    for low, name in wired.items():
        fam = _family_key(name)
        cur = fam_wired.setdefault(fam, {"max_year": 0, "example": name})
        y = _max_year(name)
        if y >= cur["max_year"]:
            cur["max_year"], cur["example"] = y, name

    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for entry in load_catalog():
        fname = entry.filename
        low = fname.lower()
        if low in wired_lower or low in seen:
            continue
        fam = _family_key(fname)
        wref = fam_wired.get(fam)
        if not wref:
            continue  # solo familias que algún conector ya usa
        variant = _has_variant_marker(fname)
        newer = _max_year(fname) > wref["max_year"] > 0
        if not (variant or newer):
            continue  # base vieja superseded → no es candidato
        seen.add(low)
        if check_live and not _head_ok(entry.url):
            continue
        out.append({
            "filename": fname, "url": entry.url, "family": fam,
            "wired_example": wref["example"],
            "reason": "variante de historia" if variant else "base más nueva",
        })
    return out


def run_bcrd_completeness_audit(
    db: Session, set_phase: Optional[Callable[[str], None]] = None, max_create: int = 20,
    check_live: bool = True,
) -> Dict[str, Any]:
    """Sube al tablero los hermanos sin cablear del catálogo BCRD (idempotente por título).
    Devuelve ``{candidates, created, capped, siblings[]}``."""
    set_phase = set_phase or (lambda _m: None)
    set_phase("cruzando conectores BCRD vs catálogo del CDN")
    siblings = find_uncabled_siblings(check_live=check_live)

    seen_titles = {
        (r.title or "").strip().lower() for r in db.query(SourceSuggestion).all()
    }
    created: List[str] = []
    capped = False
    for sib in siblings:
        if len(created) >= max_create:
            capped = True
            break
        title = f"BCRD · {sib['filename']}"
        if title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        desc = (
            f"Archivo del catálogo del CDN del BCRD NO cableado ({sib['reason']}), "
            f"hermano de la familia '{sib['family']}' que ya se conecta vía "
            f"'{sib['wired_example']}'. Evaluar si aporta más historia/cobertura. "
            f"{sib['url']}"
        )
        s = create_suggestion(
            db, kind=KIND_SOURCE, title=title[:200], description=desc[:1000],
            origin=ORIGIN_CATALOG,
        )
        created.append(s["id"])

    if capped:
        logger.info("[bcrd_completeness] cap alcanzado (%d); %d candidatos totales",
                    max_create, len(siblings))
    return {
        "candidates": len(siblings),
        "created": len(created),
        "capped": capped,
        "siblings": [s["filename"] for s in siblings],
    }
