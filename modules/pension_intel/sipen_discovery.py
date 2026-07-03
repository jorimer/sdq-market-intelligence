"""SIPEN coverage discovery — READ-ONLY ground truth of what SIPEN publishes.

Fase 0 of the SIPEN coverage audit (decision 2026-07-02, owner). Before extending
any crawler or reconciling a single caveat, we need the REAL structure of each SIPEN
page as it stands today — especially the *estados financieros auditados* section, whose
layout we have never probed (the live financials crawler only knows the interim
``/estados-financieros`` hierarchy).

This module ONLY reads: it fetches each page, parses its structure, and returns a
report. It never writes to the DB, never ingests, never mutates a score. The report
surfaces in the operations console so the owner sees, per page: which download files /
labels / years / sub-sections exist, and where the gaps are.

The pure HTML analysers (``descarga_files`` / ``section_links`` / ``download_labels``)
are offline-testable; the orchestrator (``sipen_discovery``) does the network I/O and
runs from Railway (static egress IPs + browser UA pass SIPEN's 403 bot wall).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sdq.pension_intel.sipen_discovery")

_SITE = "https://sipen.gob.do"
# The estados-financieros-afp section groups several sub-pages. We probe the PARENT to
# discover them by link (interim / auditados / accionistas / capital pagado), instead of
# guessing their paths.
EF_PARENT = f"{_SITE}/estadisticas/estados-financieros-afp"
EF_INTERIM_INDEX = f"{EF_PARENT}/estados-financieros"
EF_AUDITED_INDEX = f"{EF_PARENT}/estados-financieros-auditados"

# ── Pure HTML analysers (offline-testable) ─────────────────────────────────────
_DESCARGA_RE = re.compile(r'https://sipen\.gob\.do/descarga/[^"\'> ]+\.(?:pdf|xlsx|xls)', re.IGNORECASE)
_PERIOD_RE = re.compile(r"_(\d{4})_(\d{2})_")
_FILE_YEAR_RE = re.compile(r"(20\d{2})")
_ARIA_RE = re.compile(r'aria-label="Descargar documento ([^"]+)"', re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)


def _abs(url: str) -> str:
    if url.startswith("http"):
        return url
    return _SITE + (url if url.startswith("/") else "/" + url)


def _detect_period(url: str) -> Optional[str]:
    """A file's period from its ``_YYYY_MM_`` stamp, else a bare year from the filename,
    else None. Never guessed beyond what the URL literally carries."""
    m = _PERIOD_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    y = _FILE_YEAR_RE.search(url.rsplit("/", 1)[-1])
    return y.group(1) if y else None


def descarga_files(html: str) -> List[Dict[str, Any]]:
    """Every ``/descarga/`` file on a page → ``[{url, ext, period}]`` (deduped, ordered).

    ``period`` is the ``YYYY-MM`` stamp when present, else a bare ``YYYY``, else None."""
    seen: Dict[str, Dict[str, Any]] = {}
    for url in _DESCARGA_RE.findall(html):
        if url not in seen:
            seen[url] = {"url": url, "ext": url.rsplit(".", 1)[-1].lower(),
                         "period": _detect_period(url)}
    return list(seen.values())


def download_labels(html: str) -> List[str]:
    """The ``aria-label="Descargar documento <Title>"`` titles on a page (deduped, ordered).
    Tells us WHAT a page offers by name (e.g. 'Rentabilidad', 'Valor Cuota', 'Cartera')."""
    out: List[str] = []
    for label in _ARIA_RE.findall(html):
        t = label.strip()
        if t and t not in out:
            out.append(t)
    return out


def section_links(html: str, must_contain: str) -> List[str]:
    """Absolute hrefs whose path contains *must_contain* (deduped, ordered) — used to
    discover sub-pages under a section without hardcoding their URLs."""
    key = must_contain.lower()
    out: List[str] = []
    for href in _HREF_RE.findall(html):
        if key in href.lower():
            u = _abs(href)
            if u not in out:
                out.append(u)
    return out


def summarize_periods(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact coverage of a file list: count, distinct periods, min/max — so the report
    reads 'N archivos, 2010-01 … 2026-05' at a glance instead of a raw URL dump."""
    periods = sorted({f["period"] for f in files if f.get("period")})
    return {"n_files": len(files), "n_periods": len(periods),
            "earliest": periods[0] if periods else None,
            "latest": periods[-1] if periods else None,
            "periods": periods}


# ── Live orchestrator (network I/O; runs on Railway) ───────────────────────────

def _probe_ef_hierarchy(http, index_url: str, label: str,
                        set_phase) -> Dict[str, Any]:  # pragma: no cover - network I/O
    """Probe an estados-financieros index (interim OR audited) generically: the index's
    own /descarga files + section links, then, for each per-AFP sub-page discovered, its
    years and file coverage. Works even if the audited layout differs from the interim one
    — it reports whatever structure it actually finds, never assuming the 4-level shape."""
    from modules.pension_intel.financials_sync import (
        _afp_token, afp_page_links, file_links, year_links,
    )
    from shared.data.sipen_client import afp_catalog

    set_phase(f"Sondeando estados financieros · {label}")
    out: Dict[str, Any] = {"index": index_url}
    try:
        index_html = http.get(index_url).text
    except Exception as e:  # noqa: BLE001
        out["error"] = f"index: {e}"
        return out
    out["index_files"] = summarize_periods(descarga_files(index_html))
    out["index_labels"] = download_labels(index_html)
    out["afp_page_links"] = afp_page_links(index_html)  # {slug: url} if the interim shape holds
    out["afp_subsection_links"] = section_links(index_html, "/estados-financieros")

    # Per-AFP probe. If the interim afp_page_links keyed nothing (audited layout differs),
    # fall back to building the per-AFP URL from the token under this index.
    afps = out["afp_page_links"] or {
        slug: f"{index_url}/{_afp_token(slug)}" for slug, _ in afp_catalog()
    }
    per_afp: Dict[str, Any] = {}
    for slug, afp_url in afps.items():
        try:
            afp_html = http.get(afp_url).text
            years = year_links(afp_html, _afp_token(slug))
            afp_rec: Dict[str, Any] = {"url": afp_url, "years": sorted(years),
                                       "n_years": len(years)}
            if years:  # sample the latest year's files to learn the file shape + cadence
                y = max(years)
                files = descarga_files(http.get(years[y]).text)
                afp_rec["latest_year"] = y
                afp_rec["latest_year_files"] = summarize_periods(files)
                afp_rec["file_links_parsed"] = len(file_links(http.get(years[y]).text))
            else:
                afp_rec["direct_files"] = summarize_periods(descarga_files(afp_html))
            per_afp[slug] = afp_rec
        except Exception as e:  # noqa: BLE001 — best-effort per AFP
            per_afp[slug] = {"url": afp_url, "error": str(e)}
    out["per_afp"] = per_afp
    return out


def _probe_ckan(http) -> Dict[str, Any]:  # pragma: no cover - network I/O
    """List EVERY SIPEN dataset on datos.gob.do (not just the 3 we ingest) with its
    formats — so the report shows what national series we're leaving on the table."""
    from shared.data.sipen_client import _CKAN_DATASETS

    ingested = {d[0] for d in _CKAN_DATASETS}
    try:
        res = http.get("https://datos.gob.do/api/3/action/organization_show",
                       params={"id": "superintendencia-de-pensiones-sipen",
                               "include_datasets": "true"}).json()["result"]
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    datasets = []
    for d in res.get("packages", []) or res.get("datasets", []):
        name = d.get("name")
        datasets.append({"id": name, "title": d.get("title"),
                         "ingested": name in ingested})
    return {"org_url": "https://datos.gob.do/organization/superintendencia-de-pensiones-sipen",
            "n_datasets": len(datasets), "n_ingested": sum(d["ingested"] for d in datasets),
            "datasets": datasets}


def sipen_audited_probe(slug: str = "afp_popular",
                        set_phase=None) -> Dict[str, Any]:  # pragma: no cover - network I/O
    """READ-ONLY deep probe of ONE AFP's AUDITED statements, to settle the two open
    questions before writing the ingester (no DB writes, no persist):

      1. Are historical years ANNUAL (1 file/year) or monthly? → dump per-year file counts
         + the actual /descarga URLs for the earliest, a middle, and the latest year.
      2. Does the AI-native extractor pull patrimonio/activos from a real AUDITED PDF? →
         download the earliest annual file + the latest file and run extract → report the
         figures WITHOUT persisting.
    """
    import httpx

    from modules.pension_intel.external.financials_extractor import (
        extract_financials, map_afp_financials, statement_period,
    )
    from modules.pension_intel.financials_sync import _afp_token, file_links, year_links

    set_phase = set_phase or (lambda _m: None)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    token = _afp_token(slug)
    afp_url = f"{EF_AUDITED_INDEX}/{token}"
    out: Dict[str, Any] = {"slug": slug, "afp_url": afp_url, "per_year": {}, "extractions": []}

    def _trial_extract(http, label, url):
        set_phase(f"Extrayendo (prueba, sin persistir) · {label}")
        try:
            content = http.get(url).content
            fname = url.rsplit("/", 1)[-1]
            statements = extract_financials(content, fname)
            fields = map_afp_financials(statements)
            out["extractions"].append({
                "label": label, "url": url, "filename": fname,
                "period": statement_period(statements),
                "patrimonio": fields.get("patrimonio"),
                "activos_totales": fields.get("activos_totales"),
                "fondos_administrados": fields.get("fondos_administrados"),
                "comisiones": fields.get("comisiones"),
            })
        except Exception as e:  # noqa: BLE001
            out["extractions"].append({"label": label, "url": url, "error": str(e)})

    with httpx.Client(timeout=120, headers=headers, follow_redirects=True) as http:
        set_phase(f"Sondeo auditado · {slug} · años")
        try:
            years = year_links(http.get(afp_url).text, token)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"afp page: {e}"
            return out
        ys = sorted(years)
        out["years"] = ys
        # Per-year file coverage for EVERY year (annual vs monthly at a glance).
        for y in ys:
            try:
                files = descarga_files(http.get(years[y]).text)
                out["per_year"][y] = {"n_files": len(files),
                                      "periods": [f["period"] for f in files],
                                      "urls": [f["url"] for f in files]}
            except Exception as e:  # noqa: BLE001
                out["per_year"][y] = {"error": str(e)}
        # Trial extraction: earliest annual file + the latest file.
        if ys:
            first_urls = out["per_year"].get(ys[0], {}).get("urls") or []
            last_urls = out["per_year"].get(ys[-1], {}).get("urls") or []
            if first_urls:
                _trial_extract(http, f"{slug} {ys[0]} (más antiguo)", first_urls[-1])
            if last_urls:
                _trial_extract(http, f"{slug} {ys[-1]} (más reciente)", last_urls[-1])
    set_phase("Sondeo auditado completo (read-only)")
    return out


def sipen_discovery(set_phase=None) -> Dict[str, Any]:  # pragma: no cover - network I/O
    """READ-ONLY: probe every SIPEN publication surface and return a structured coverage
    report. No DB writes, no ingest. Best-effort per page (one failure never aborts the
    rest). Runs from Railway (static egress + browser UA pass SIPEN's bot wall)."""
    import httpx

    from shared.data.sipen_client import (
        _BOLETIN_PAGE, _PREVISIONAL_PAGE, boletin_pdf_links, previsional_xlsx_links,
    )

    set_phase = set_phase or (lambda _m: None)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    report: Dict[str, Any] = {"probed_at": date.today().isoformat(), "pages": {}}
    pages = report["pages"]

    with httpx.Client(timeout=90, headers=headers, follow_redirects=True) as http:
        # B — Estadística Previsional: ALL labelled XLSX (we ingest only 'rentabilidad').
        set_phase("Sondeando Estadística Previsional")
        try:
            html = http.get(_PREVISIONAL_PAGE).text
            xlsx = previsional_xlsx_links(html)
            pages["previsional"] = {
                "url": _PREVISIONAL_PAGE, "download_labels": download_labels(html),
                "xlsx_links": sorted(xlsx.keys()), "n_xlsx": len(xlsx),
                "ingested_labels": ["rentabilidad"],
            }
        except Exception as e:  # noqa: BLE001
            pages["previsional"] = {"url": _PREVISIONAL_PAGE, "error": str(e)}

        # C — Boletines Trimestrales: how many, latest number.
        set_phase("Sondeando Boletines Trimestrales")
        try:
            links = boletin_pdf_links(http.get(_BOLETIN_PAGE).text)
            pages["boletines"] = {
                "url": _BOLETIN_PAGE, "n_boletines": len(links),
                "latest_num": max((n for n, _ in links), default=None),
                "numbers": sorted((n for n, _ in links), reverse=True)[:12],
            }
        except Exception as e:  # noqa: BLE001
            pages["boletines"] = {"url": _BOLETIN_PAGE, "error": str(e)}

        # D — Estados financieros: discover the sub-sections under the PARENT, then probe
        # the interim and audited indexes generically (audited layout is unknown).
        set_phase("Descubriendo sub-secciones de estados financieros")
        try:
            parent_html = http.get(EF_PARENT).text
            pages["estados_financieros_parent"] = {
                "url": EF_PARENT,
                "subsection_links": section_links(parent_html, "/estados-financieros-afp/"),
                "labels": download_labels(parent_html),
            }
        except Exception as e:  # noqa: BLE001
            pages["estados_financieros_parent"] = {"url": EF_PARENT, "error": str(e)}

        pages["ef_interinos"] = _probe_ef_hierarchy(http, EF_INTERIM_INDEX, "interinos", set_phase)
        pages["ef_auditados"] = _probe_ef_hierarchy(http, EF_AUDITED_INDEX, "auditados", set_phase)

        # A — CKAN: every SIPEN dataset (we ingest only 3).
        set_phase("Sondeando CKAN datos.gob.do")
        pages["ckan"] = _probe_ckan(http)

    # Headline summary for the console (the owner reads this line first).
    aud = pages.get("ef_auditados", {})
    aud_afps = aud.get("per_afp", {}) if isinstance(aud, dict) else {}
    aud_with_years = sum(1 for r in aud_afps.values() if isinstance(r, dict) and r.get("years"))
    report["summary"] = {
        "previsional_xlsx": pages.get("previsional", {}).get("n_xlsx"),
        "boletines": pages.get("boletines", {}).get("n_boletines"),
        "auditados_afps_con_años": aud_with_years,
        "auditados_index_reachable": "error" not in aud,
        "ckan_datasets": pages.get("ckan", {}).get("n_datasets"),
    }
    set_phase("Descubrimiento completo (read-only)")
    return report
