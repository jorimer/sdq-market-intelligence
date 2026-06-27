"""Fiduciary ETL — discover + parse audited PDFs from the SIB supervised portal.

The SIB *statistics API* does not expose fiduciaries, but the *supervised-entities
portal* (``sb.gob.do/supervisados/fiduciarias/<slug>/``) publishes their audited
annual statements as PDFs (server-side links in the page HTML). This client:

1. Discovers the PDF links per entity (entity statements + public-trust statements).
2. Downloads a PDF and runs the AI extractor (``audited_pdf_extractor``).
3. Maps the extracted line items to the figures the scoring needs:
   - Entities  → ``BankingData`` fields (rated with the ``fiduciaria`` profile).
   - Trusts    → a small dict for the trust health index.

Discovery verified 2026-06-10. Only Fiduciaria Reservas publishes individual
public-trust statements (it manages the State's trusts); the others publish only
their own entity statements; FiduAPAP publishes none.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "SDQ-MIP/1.0"}

PORTAL_BASE = "https://www.sb.gob.do"
_FIDU_PATH = "/supervisados/fiduciarias"

# slug → display name. The 5 supervised fiduciaries (discovery 2026-06-10).
FIDUCIARY_ENTITIES: Dict[str, str] = {
    "fiduciaria-reservas": "Fiduciaria Reservas",
    "fiduciaria-bhd": "Fiduciaria BHD",
    "fiduciaria-popular": "Fiduciaria Popular",
    "fiduciaria-la-nacional": "Fiduciaria La Nacional",
    "fiduapap": "FiduAPAP",
}

# Public-trust filename stems (entity statements are "NN-de-diciembre-YYYY" or
# "...auditados...YYYY"). Anything whose stem starts with one of these prefixes is a
# trust, not the entity. Derived from the Reservas page (the only one with trusts).
_TRUST_STEMS = (
    "fdi", "confie", "pnd", "fotesir", "masgas", "parqueate", "mivivienda",
    "fonvivienda", "ftpn", "cohesionado", "rd-vial", "pro-pedernales", "fitram",
    "fimerca", "fimovit", "vbc-rd", "do-sostenible", "desarrollo-sostenible",
    "filantr", "creditos-educativos",
)

_PDF_RE = re.compile(r'/media/[a-z0-9]+/[^"\'> ]+\.pdf', re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")


def _html_decode(s: str) -> str:
    import html

    return html.unescape(s)


def _strip_accents(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _stem(url: str) -> str:
    """Last path segment without extension, lowercased (HTML-decoded, accent-free)."""
    raw = _html_decode(url.rsplit("/", 1)[-1])
    return _strip_accents(os.path.splitext(raw)[0].lower())


def _classify(url: str) -> Tuple[str, Optional[int]]:
    """Classify a PDF link → ("entity"|"trust", year). Year may be None."""
    stem = _stem(url)
    ym = _YEAR_RE.search(stem)
    year = int(ym.group(1)) if ym else None
    if any(stem.startswith(p) for p in _TRUST_STEMS):
        return "trust", year
    return "entity", year


def discover_pdfs(slug: str, timeout: int = 30) -> Dict[str, List[Tuple[Any, str]]]:  # pragma: no cover - network
    """Scrape an entity page for its statement PDFs.

    Returns {"entity": [(year, abs_url), ...], "trusts": [(name, abs_url), ...]}.
    """
    url = f"{PORTAL_BASE}{_FIDU_PATH}/{slug}/"
    resp = httpx.get(url, timeout=timeout, headers=_HEADERS, follow_redirects=True)
    resp.raise_for_status()
    html = resp.text

    seen: set[str] = set()
    entity: List[Tuple[Any, str]] = []
    trusts: List[Tuple[Any, str]] = []
    for m in _PDF_RE.finditer(html):
        path = _html_decode(m.group(0))
        if path in seen:
            continue
        seen.add(path)
        abs_url = f"{PORTAL_BASE}{path}"
        kind, year = _classify(path)
        if kind == "trust":
            name = _trust_name(path)
            trusts.append((name, abs_url))
        else:
            entity.append((year, abs_url))

    entity.sort(key=lambda t: (t[0] or 0), reverse=True)
    trusts.sort(key=lambda t: t[0])
    return {"entity": entity, "trusts": trusts}


def _trust_name(url: str) -> str:
    """Human-ish trust name from the filename stem (strip the date suffix)."""
    stem = _html_decode(_stem(url))
    stem = re.sub(r"-?\d{1,2}-de-\w+-20\d{2}$", "", stem)
    stem = re.sub(r"-?31-de-diciembre-20\d{2}$", "", stem)
    return stem.replace("-", " ").strip().upper() or stem.upper()


def download_pdf(url: str, timeout: int = 120) -> str:  # pragma: no cover - network
    """Download a PDF to a temp file; return its path (caller deletes it)."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with httpx.stream("GET", url, timeout=timeout, headers=_HEADERS, follow_redirects=True) as resp:
            resp.raise_for_status()
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


# ─── Line-item helpers ───────────────────────────────────────────────────

def _num(item: Dict[str, Any], key: str = "amount_current") -> Optional[float]:
    v = item.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _find_total(items: List[Dict[str, Any]], category: str, *label_keywords: str) -> Optional[float]:
    """Find a grand-total amount: prefer is_total rows of *category* whose
    original_text contains any keyword; else any row matching the keywords."""
    kw = [k.lower() for k in label_keywords]

    def matches(it: Dict[str, Any]) -> bool:
        txt = (it.get("original_text") or "").lower()
        return any(k in txt for k in kw)

    # 1) is_total + right category + keyword
    for it in items:
        if it.get("is_total") and (it.get("category") == category) and matches(it):
            v = _num(it)
            if v is not None:
                return v
    # 2) is_total + keyword (any category)
    for it in items:
        if it.get("is_total") and matches(it):
            v = _num(it)
            if v is not None:
                return v
    # 3) keyword only (last resort)
    for it in items:
        if matches(it):
            v = _num(it)
            if v is not None:
                return v
    return None


def _find_equity_result(items: List[Dict[str, Any]], *label_keywords: str) -> Optional[float]:
    """Find the period result inside the equity section (a non-total equity row
    like 'Resultado del período' under Patrimonio fideicomitido)."""
    kw = [k.lower() for k in label_keywords]
    for it in items:
        if it.get("is_total"):
            continue
        if it.get("category") != "equity":
            continue
        txt = (it.get("original_text") or "").lower()
        if any(k in txt for k in kw):
            v = _num(it)
            if v is not None:
                return v
    return None


def _last_income_total(items: List[Dict[str, Any]]) -> Optional[float]:
    """The bottom line of an income statement — last is_total row whose label looks
    like a result (not 'Total ingresos'/'Total gastos', not zero). Fallback for the
    net result when no explicit result label matched."""
    candidate = None
    for it in items:
        if not it.get("is_total"):
            continue
        txt = (it.get("original_text") or "").lower()
        if "ingreso" in txt or "gasto" in txt:  # skip revenue/expense subtotals
            continue
        v = _num(it)
        if v is not None and v != 0:  # skip nil "otro resultado integral" rows
            candidate = v  # keep the last qualifying non-zero total
    return candidate


def _sum_matching(items: List[Dict[str, Any]], *label_keywords: str) -> Optional[float]:
    """Sum non-total line items whose label contains a keyword (e.g. efectivo +
    inversiones for liquid assets). Returns None if nothing matched."""
    kw = [k.lower() for k in label_keywords]
    total = 0.0
    hit = False
    for it in items:
        if it.get("is_total") or it.get("is_subtotal"):
            continue
        txt = (it.get("original_text") or "").lower()
        if any(k in txt for k in kw):
            v = _num(it)
            if v is not None:
                total += v
                hit = True
    return round(total, 2) if hit else None


# ─── Mappers: extracted statements → scoring fields ──────────────────────

def map_entity_fields(statements: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Map an extracted fiduciary-entity statement to BankingData-style fields.
    Missing figures stay ``None`` (N/D — never fabricated)."""
    bg = statements.get("balance_general", [])
    er = statements.get("estado_resultados", [])

    # Singular "total activo"/"total pasivo" are SIB-regulatory labels (e.g. SIPEN's AFP
    # statements). They're substrings of the plural forms, so one keyword covers both.
    activos = _find_total(bg, "assets", "total activos", "total de activos", "total activo")
    pasivos = _find_total(bg, "liabilities", "total pasivos", "total de pasivos", "total pasivo")
    patrimonio = _find_total(
        bg, "equity", "total patrimonio", "patrimonio fideicom", "total de patrimonio",
        "patrimonio neto", "patrimonio de los accionistas", "capital contable", "total capital",
    )
    # Fallback by the accounting identity (Activos = Pasivos + Patrimonio) when the
    # equity total isn't labelled in a way we matched.
    if patrimonio is None and activos is not None and pasivos is not None:
        patrimonio = round(activos - pasivos, 2)
    liquidos = _sum_matching(bg, "efectivo", "equivalentes de efectivo", "inversiones", "depósitos a plazo", "depositos a plazo")
    pasivos_circ = _find_total(bg, "liabilities", "total pasivos circulantes", "total pasivos corrientes")

    ingresos = _find_total(er, "revenue", "total ingresos", "total de ingresos", "total ingresos operacionales")
    gastos_op = _find_total(er, "opex", "total gastos operacionales", "total gastos de operaci", "total gastos", "gastos operacionales")
    if gastos_op is not None:
        gastos_op = abs(gastos_op)  # statements show expenses in () → keep magnitude
    comisiones = _sum_matching(er, "comisiones fiduciarias", "comisiones")
    resultado = _find_total(
        er, "net_income", "resultado neto", "utilidad neta", "ganancia neta",
        "excedente", "resultado del ejercicio", "utilidad del ejercicio", "resultado integral",
        "resultado del período", "resultado del periodo", "resultado del año",
        "utilidad del período", "utilidad del periodo", "ganancia del", "beneficio neto",
    )
    if resultado is None or resultado == 0:
        fallback = _last_income_total(er)  # bottom line of the income statement
        if fallback:
            resultado = fallback

    return {
        "activos_totales": activos,
        "pasivos_exigibles": pasivos,
        "pasivos_cp": pasivos_circ,
        "patrimonio_tecnico": patrimonio,
        "activos_liquidos": liquidos,
        "ingresos_operacionales": ingresos,
        "gastos_operacionales": gastos_op,
        "comisiones_fiduciarias": comisiones,
        "utilidad_neta": resultado,
    }


def map_trust_fields(statements: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Map an extracted trust (fideicomiso) statement to health-index fields."""
    bg = statements.get("balance_general", [])
    er = statements.get("estado_resultados", [])

    # Singular "total activo"/"total pasivo" are SIB-regulatory labels (e.g. SIPEN's AFP
    # statements). They're substrings of the plural forms, so one keyword covers both.
    activos = _find_total(bg, "assets", "total activos", "total de activos", "total activo")
    pasivos = _find_total(bg, "liabilities", "total pasivos", "total de pasivos", "total pasivo")
    patrimonio = _find_total(bg, "equity", "total patrimonio fideicom", "patrimonio fideicom", "total patrimonio")
    pasivos_circ = _find_total(bg, "liabilities", "total pasivos circulantes", "total pasivos corrientes")
    liquidos = _sum_matching(bg, "efectivo", "equivalentes de efectivo", "depósitos a plazo", "depositos a plazo", "inversiones")
    ingresos = _find_total(er, "revenue", "total ingresos operacionales", "total ingresos")

    # Net result: trusts show "Resultado del período" inside the equity section of
    # the balance (Aportes + Resultado = Total patrimonio fideicomitido). Prefer
    # that; fall back to a net row in the income statement.
    _RES_KW = (
        "resultado del período", "resultado del periodo", "resultado integral",
        "resultado del ejercicio", "excedente", "déficit", "deficit", "beneficios",
        "resultado neto",
    )
    resultado = _find_equity_result(bg, *_RES_KW)
    if resultado is None:
        resultado = _find_total(er, "net_income", *_RES_KW)
    if resultado is None:
        resultado = _last_income_total(er)  # bottom line of the income statement

    return {
        "activos_totales": activos,
        "pasivos_totales": pasivos,
        "pasivos_circulantes": pasivos_circ,
        "patrimonio_fideicomitido": patrimonio,
        "activos_liquidos": liquidos,
        "resultado_periodo": resultado,
        "ingresos_operacionales": ingresos,
    }
