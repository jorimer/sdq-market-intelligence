"""Sovereign credit ratings scraper — Wikipedia (free, policy-compliant).

Source: **"List of countries by credit rating"** via the MediaWiki API
(``action=parse&prop=wikitext``). The API is the sanctioned access path — Wikipedia's
bot policy 403s raw-HTML scraping with a generic client — and returns stable,
deterministic wikitext. Requires a descriptive ``User-Agent`` with contact info per the
Wikimedia UA policy.

The page keeps three per-agency tables (Standard & Poor's / Fitch / Moody's); each data
row is a wikitable line of the form::

    | {{flag|Country}} || data-sort-value=N | {{Percentage bar|100|c=#col;|BB−|…}} ||
      data-sort-value=N | Stable&nbsp;{{Steady}} || 19 December 2022 || <ref>…</ref>

We parse only the DO·CR·PA·GT·JM panel, normalize the Unicode minus (``BB−`` → ``BB-``) to
the S&P notation of ``rating_scale``, keep the last-**action** date (ISO), the outlook and
the reference URL. Best-effort: any fetch/parse failure returns ``{}`` and the caller keeps
the declared yaml floor (never fabricates a rating). The pure parser is unit-tested against
a committed real wikitext fixture.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger("sdq.data.sovereign")

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List_of_countries_by_credit_rating"
# Wikimedia UA policy: identify the tool + a contact. Generic UAs are 403'd.
USER_AGENT = (
    "SDQ-MIP/1.0 (https://sdqconsulting.com.do; contacto@sdqconsulting.com.do) "
    "sovereign-ratings-sync"
)

# Wikipedia country label (inside {{flag|…}}) → ISO2 of our peer panel. Only these five
# are extracted; every other row is ignored.
PANEL: Dict[str, str] = {
    "Dominican Republic": "DO",
    "Costa Rica": "CR",
    "Panama": "PA",
    "Guatemala": "GT",
    "Jamaica": "JM",
}

# Section heading (== … ==) → agency slug used throughout the store.
_AGENCY_HEADINGS: Dict[str, str] = {
    "Standard & Poor's": "sp",
    "Fitch": "fitch",
    "Moody's": "moodys",
}

_MONTHS: Dict[str, str] = {
    m: f"{i:02d}" for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"], 1)
}

_HEADING_RE = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.MULTILINE)
_FLAG_RE = re.compile(r"\{\{\s*flag(?:icon)?\s*\|\s*([^|}]+?)\s*[|}]")
# Rating inside {{Percentage bar|<num>|c=<color>|<RATING>|color=…}} — the token after the
# colour arg. Tolerant of spacing.
_RATING_RE = re.compile(
    r"\{\{\s*Percentage bar\s*\|[^|}]*\|\s*c=[^|}]*\|\s*([^|}]+?)\s*\|", re.IGNORECASE)
_OUTLOOK_RE = re.compile(r"\b(Positive|Stable|Negative|Developing)\b")
_DATE_CELL_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
_URL_RE = re.compile(r"url\s*=\s*(https?://[^\s|}\]]+)", re.IGNORECASE)


def _normalize_rating(raw: str) -> str:
    """Wikipedia notation → S&P notation of ``rating_scale``: normalize the several dash
    glyphs (Unicode minus ``−`` U+2212, en/em dashes) to ASCII ``-`` and trim."""
    return (raw.replace("−", "-").replace("–", "-").replace("—", "-")
            .strip())


def _parse_date(cell: str) -> Optional[str]:
    """``'19 December 2022'`` → ``'2022-12-19'`` (ISO), or None if not a clean date cell."""
    m = _DATE_CELL_RE.match(cell.strip())
    if not m:
        return None
    day, month, year = m.group(1), m.group(2).lower(), m.group(3)
    mm = _MONTHS.get(month)
    if not mm:
        return None
    return f"{year}-{mm}-{int(day):02d}"


def _parse_row(row: str) -> Optional[Dict[str, Optional[str]]]:
    """Parse one wikitable row → ``{rating, outlook, action_date, source_url}`` for a panel
    country, or None if the row isn't a target country / lacks a rating. Never guesses a
    missing field (stays None)."""
    fm = _FLAG_RE.search(row)
    if not fm or fm.group(1).strip() not in PANEL:
        return None
    iso = PANEL[fm.group(1).strip()]

    rm = _RATING_RE.search(row)
    if not rm:
        return None  # no machine-readable rating → skip (don't fabricate)
    rating = _normalize_rating(rm.group(1))

    cells = row.split("||")
    outlook: Optional[str] = None
    action_date: Optional[str] = None
    for cell in cells:
        c = cell.strip()
        if action_date is None:
            # date cell holds only the date (refs live in their own cell); this avoids
            # picking an access-date out of a <ref>.
            iso_date = _parse_date(re.sub(r"^data-sort-value=[^|]*\|", "", c).strip())
            if iso_date:
                action_date = iso_date
                continue
        if outlook is None and "Percentage bar" not in cell:
            om = _OUTLOOK_RE.search(cell)
            if om:
                outlook = om.group(1)
    um = _URL_RE.search(row)
    return {
        "iso": iso, "rating": rating, "outlook": outlook,
        "action_date": action_date, "source_url": um.group(1) if um else None,
    }


def parse_credit_rating_wikitext(
    wikitext: str,
) -> Dict[str, Dict[str, Dict[str, Optional[str]]]]:
    """Parse the article wikitext → ``{iso2: {agency: {rating, outlook, action_date,
    source_url}}}`` for the DO·CR·PA·GT·JM panel across S&P/Fitch/Moody's.

    Pure (no network) — the unit under test. Splits the page into the three per-agency
    sections by their headings, then each section's rows by the wikitable ``|-`` separator.
    Rows for non-panel countries or without a rating are skipped, never invented."""
    headings = [(m.start(), m.group(1).strip()) for m in _HEADING_RE.finditer(wikitext)]
    out: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
    for idx, (pos, name) in enumerate(headings):
        agency = _AGENCY_HEADINGS.get(name)
        if not agency:
            continue
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(wikitext)
        body = wikitext[pos:end]
        for row in body.split("|-"):
            parsed = _parse_row(row)
            if parsed is None:
                continue
            iso = parsed.pop("iso")
            out.setdefault(iso, {})[agency] = parsed
    return out


def fetch_sovereign_ratings() -> Dict[str, Dict[str, Dict[str, Optional[str]]]]:  # pragma: no cover - network I/O
    """LIVE: fetch + parse the Wikipedia credit-rating panel → ``{iso: {agency: {…}}}``.

    Best-effort: any network/parse failure logs and returns ``{}`` so the caller keeps the
    declared yaml floor. Runs in ``sovereign-ratings-sync``; offline/tests use the parser
    directly against the fixture."""
    import httpx

    params = {
        "action": "parse", "page": WIKI_PAGE, "prop": "wikitext",
        "format": "json", "formatversion": "2",
    }
    try:
        with httpx.Client(timeout=40, headers={"User-Agent": USER_AGENT},
                          follow_redirects=True) as http:
            data = http.get(WIKI_API, params=params).json()
        wikitext = data["parse"]["wikitext"]
    except Exception as e:  # noqa: BLE001 — best-effort; keep the floor
        logger.warning("[SOVEREIGN] no se pudo traer Wikipedia: %s", e)
        return {}
    panel = parse_credit_rating_wikitext(wikitext)
    if not panel:
        logger.warning("[SOVEREIGN] Wikipedia parseado pero sin filas del panel")
    return panel
