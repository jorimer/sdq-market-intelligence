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


# quarter label → 1..4. Covers BCRD's many spellings: month-range ("E-M", "A-J",
# "J-S", "O-D"; "Ene-Mar"), Roman ("I".."IV"), and "T1"/"1T"/"Trim 1"/"Q1".
#: Los rótulos del cuadro ACUMULADO: el rango va siempre desde enero, y el trimestre es aquel
#: en que CIERRA. El BCRD publica cada cuadro trimestral dos veces —el flujo del trimestre
#: (`A-J` = abril-junio) y el acumulado del año (`E-J` = enero-junio)— y solo estaban los
#: primeros: los otros tres no resolvían trimestre, caían al AÑO, y las tres columnas de un
#: año competían por la misma clave. El dedupe «último gana» dejaba una arbitraria. En el PIB
#: por sector de origen eran 1.660 duplicados con valores distintos.
#:
#: `E-M` (enero-marzo) no está acá a propósito: es el primer trimestre en los DOS cuadros y
#: vale lo mismo en ambos, así que no distingue uno de otro.
_QUARTERS_ACUMULADOS: dict[str, int] = {
    "e-j": 2, "e-s": 3, "e-d": 4,
    "ene-jun": 2, "ene-sep": 3, "ene-dic": 4,
    "enero-junio": 2, "enero-septiembre": 3, "enero-diciembre": 4,
}

_QUARTERS: dict[str, int] = {
    **_QUARTERS_ACUMULADOS,
    "e-m": 1, "a-j": 2, "j-s": 3, "o-d": 4,
    "ene-mar": 1, "abr-jun": 2, "jul-sep": 3, "oct-dic": 4,
    # Con los meses COMPLETOS: así rotula el tipo de cambio sus cortes trimestrales
    # (`Enero-Marzo`, `Abril-Junio`). Estaban solo las formas abreviadas, y sin trimestre
    # las cuatro filas de cada año colapsaban en el año — 367 valores en conflicto.
    "enero-marzo": 1, "abril-junio": 2, "julio-septiembre": 3, "octubre-diciembre": 4,
    "ene-marzo": 1, "i": 1, "ii": 2, "iii": 3, "iv": 4,
    "t1": 1, "t2": 2, "t3": 3, "t4": 4,
    "1t": 1, "2t": 2, "3t": 3, "4t": 4,
    "q1": 1, "q2": 2, "q3": 3, "q4": 4,
    "trim1": 1, "trim2": 2, "trim3": 3, "trim4": 4,
}


def parse_quarter(value: Any) -> Optional[int]:
    """``"E-M"`` / ``"Ene-Mar"`` / ``"III"`` / ``"T2"`` / ``"Q4"`` → 1..4; else None."""
    token = normalize_label(value).rstrip(".").strip()
    if not token:
        return None
    compact = token.replace(" ", "").replace("trimestre", "trim")
    if compact in _QUARTERS:
        return _QUARTERS[compact]
    # "trim 1" / "1er trimestre" style → trailing/leading digit 1..4
    m = re.search(r"\b([1-4])\b", token)
    if m and ("trim" in token or "t" == token[:1]):
        return int(m.group(1))
    return None


def es_trimestre_acumulado(value: Any) -> bool:
    """¿El rótulo denota un acumulado del año (enero a…) en vez del flujo del trimestre?

    Lo decide el ENCABEZADO del cuadro, que es donde el emisor lo declara — no el nombre del
    archivo ni una lista escrita a mano. Sirve para que la serie extraída diga en su código
    que es acumulada: sin eso, el acumulado y el flujo comparten sujeto, unidad y período, y
    quien agrupe por el nombre de la serie sumaría los dos.
    """
    token = normalize_label(value).rstrip(".").strip().replace(" ", "")
    return token in _QUARTERS_ACUMULADOS


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


def format_period(year: int, month: Optional[int], quarter: Optional[int] = None,
                  day: Optional[int] = None) -> str:
    """``(2007, 5) → "2007-05"``; ``(2007, None, 2) → "2007-Q2"``; ``(2007, None) → "2007"``;
    ``(2007, 5, day=9) → "2007-05-09"``.

    El DÍA es la cuarta forma de período de la plataforma. Existe porque el tipo de cambio se
    publica diario: sin día, los ~22 días hábiles de un mes colapsaban en `YYYY-MM` y el
    upsert dejaba uno arbitrario — 19.680 valores en conflicto en un solo archivo.
    """
    if month is not None and day is not None:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if month is not None:
        return f"{int(year):04d}-{int(month):02d}"
    if quarter is not None:
        return f"{int(year):04d}-Q{int(quarter)}"
    return f"{int(year):04d}"


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
