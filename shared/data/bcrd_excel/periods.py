"""Period & number normalization for the BCRD Excel corpus.

The BCRD spells months in Spanish (full and abbreviated, with/without accents and
trailing dots), writes years as ``1982``, ``1982.0`` or ``"1982"`` interchangeably,
and stores numeric cells as floats *or* as strings (``'255'`` vs ``312.7``). These
helpers collapse that mess into stable ``"YYYY-MM"`` / ``"YYYY"`` periods and
``float | None`` values.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# month name (accent/dot/abbrev-insensitive) → 1..12
_MONTHS: dict[str, int] = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "set": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalize_label(value: Any) -> str:
    """Lowercase, accent-stripped, trimmed text of a cell (``''`` for empty)."""
    if value is None:
        return ""
    return strip_accents(str(value)).lower().strip()


def parse_month(value: Any) -> Optional[int]:
    """``"Septiembre"`` / ``"Dic."`` / ``"ene"`` → 1..12; None if not a month."""
    token = normalize_label(value).rstrip(".").strip()
    if not token:
        return None
    if token in _MONTHS:
        return _MONTHS[token]
    # first whitespace-delimited word (handles "Dic. 2007" style cells)
    first = token.split()[0].rstrip(".")
    return _MONTHS.get(first)


def parse_year(value: Any) -> Optional[int]:
    """``1982`` / ``1982.0`` / ``"1982"`` → 1982; None if not a plausible year."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        y = int(value)
        return y if 1900 <= y <= 2100 else None
    m = re.search(r"(19|20)\d{2}", str(value))
    if not m:
        return None
    y = int(m.group(0))
    return y if 1900 <= y <= 2100 else None


def format_period(year: int, month: Optional[int]) -> str:
    """``(2007, 5) → "2007-05"``; ``(2007, None) → "2007"`` (annual)."""
    if month is None:
        return f"{int(year):04d}"
    return f"{int(year):04d}-{int(month):02d}"


def coerce_num(value: Any) -> Optional[float]:
    """Cell → ``float``; ``None`` for blanks, dashes and non-numeric text.

    BCRD uses ``-``/``n.d.``/``...`` for missing — these stay ``None`` (never
    interpolated). Thousands separators (``1,234.5`` and the es-DO ``1.234,5``)
    are tolerated when unambiguous.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if f != f else f  # drop NaN
    s = str(value).strip()
    if not s or s in {"-", "--", "...", "n.d.", "nd", "n/d", "N.D.", "N/D"}:
        return None
    s = s.replace("%", "").replace("US$", "").replace("RD$", "").strip()
    # es-DO grouping "1.234,5" → "1234.5"; en grouping "1,234.5" → "1234.5"
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # ambiguous: treat as decimal comma only when it looks like one (",dd")
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None
