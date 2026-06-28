"""Extract the pension funds' investment portfolio from the SIPEN bulletin.

Source: *Cuadro 6.1 — Composición de la cartera de inversiones de los fondos de
pensiones por emisor (RD$)* in the quarterly Boletín Trimestral (PDF). The bulletin
is machine-readable text (NOT scanned), but the table has **no ruled grid**, so
``pdfplumber.extract_tables()`` returns nothing. Columns are right-aligned at fixed
X positions, and pdfplumber splits some amounts on a hair-space ("3 2,027,246,695.76"),
so a per-line regex is fragile.

Approach (verified 2026-06-28): a **deterministic positional parser** keyed on column
X-bands — the name is the left block, each amount is the words that fall inside the
column band (re-joined → the split digit is healed). Group-header rows (sub-sector
subtotals) are detected **structurally** (a row whose amount equals the sum of the
contiguous following rows), so we don't hardcode the sub-sector list and new categories
(Fondos de Inversión, Fideicomisos de Oferta Pública) are picked up automatically. The
leaf issuers then reconcile to the table TOTAL — if they don't (±tolerance), extraction
**fails closed** (raises) rather than persisting unverified figures.

PR1 reads the **"Subtotal Fondos CCI"** column (the system portfolio, ≈RD$1.3B ≈90% of
the total); the per-complementary-fund columns and the grand TOTAL are a later phase.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Column X-bands for the "Subtotal Fondos CCI" pair (the first amount/pct after the
# issuer name). Layout-specific by nature; the TOTAL reconciliation guards them — if a
# future bulletin shifts the columns, the leaves won't sum to TOTAL and we fail closed.
_NAME_MAX_X = 200.0
_CCI_MONTO_X = (235.0, 292.0)
_CCI_PCT_X = (293.0, 320.0)
_RECONCILE_TOL = 0.005  # 0.5% — leaves vs TOTAL

_MONTHS_Q = {
    "enero": "Q1", "febrero": "Q1", "marzo": "Q1",
    "abril": "Q2", "mayo": "Q2", "junio": "Q2",
    "julio": "Q3", "agosto": "Q3", "septiembre": "Q3",
    "octubre": "Q4", "noviembre": "Q4", "diciembre": "Q4",
}


class CarteraExtractionError(RuntimeError):
    """The Cuadro 6.1 portfolio table was not found or did not reconcile."""


@dataclass
class Holding:
    """One parsed portfolio line (before lineage/cross-keys are stamped)."""
    sub_sector: Optional[str]
    issuer: str
    issuer_slug: str
    amount: Optional[float]
    pct: Optional[float]
    is_subtotal: bool
    macro_class: Optional[str] = None


def issuer_slug(label: str) -> str:
    """Stable key for an issuer label (accent/case-insensitive, snake_case)."""
    norm = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", norm.lower()).strip("_")


def _macro_class(issuer: str) -> Optional[str]:
    """Deterministic Macro cross-key from the issuer (no cross-module table access)."""
    low = issuer.lower()
    if "ministerio de hacienda" in low:
        return "deuda_publica"
    if "banco central" in low:
        return "bcrd"
    return None


def _num(tokens: List[str]) -> Optional[float]:
    """Join amount-column tokens → float; '-'/blank → None (heals the split-digit)."""
    s = "".join(tokens).replace(" ", "").replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def cartera_period(text: str) -> Optional[str]:
    """Quarter label from the table's "Al DD de <mes> de YYYY" cut-off → "YYYY-Qn"."""
    m = re.search(r"al\s+\d{1,2}\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", text.lower())
    if not m:
        return None
    q = _MONTHS_Q.get(m.group(1))
    return f"{m.group(2)}-{q}" if q else None


def _rows_from_words(words: List[Dict]) -> List[Tuple[str, Optional[float], Optional[float]]]:
    """Group words into visual lines → ``[(name, cci_amount, cci_pct)]``."""
    lines: Dict[int, List[Dict]] = defaultdict(list)
    for w in words:
        lines[round(w["top"])].append(w)
    out: List[Tuple[str, Optional[float], Optional[float]]] = []
    for _top, ws in sorted(lines.items()):
        ws = sorted(ws, key=lambda w: w["x0"])
        name = " ".join(w["text"] for w in ws if w["x1"] < _NAME_MAX_X).strip()
        if not name:
            continue
        monto_tok = [w["text"] for w in ws
                     if w["x0"] >= _CCI_MONTO_X[0] and w["x1"] <= _CCI_MONTO_X[1]]
        pct_tok = [w["text"] for w in ws
                   if _CCI_PCT_X[0] <= (w["x0"] + w["x1"]) / 2 <= _CCI_PCT_X[1]]
        amount = _num(monto_tok)
        pct = _num([pct_tok[0].replace("%", "")]) if pct_tok else None
        out.append((name, amount, pct))
    return out


def parse_cartera_words(words: List[Dict]) -> List[Holding]:
    """Parse Cuadro 6.1 word boxes → reconciled list of :class:`Holding` (CCI column).

    Group headers are detected structurally (amount == sum of the contiguous following
    rows); their children inherit the header's name as ``sub_sector``. Leaf issuers must
    sum to the table TOTAL (±0.5%) or :class:`CarteraExtractionError` is raised."""
    rows = _rows_from_words(words)

    total: Optional[float] = None
    body: List[Tuple[str, Optional[float], Optional[float]]] = []
    for name, amount, pct in rows:
        if name.upper().startswith("TOTAL") and amount is not None:
            total = amount
        elif amount is not None:
            body.append((name, amount, pct))
    if total is None:
        raise CarteraExtractionError("Cuadro 6.1: no se encontró la fila TOTAL")

    # Structural header detection: a row whose amount == sum of the contiguous following
    # rows is a sub-sector subtotal; those rows are its children.
    n = len(body)
    is_header = [False] * n
    child_parent: Dict[int, int] = {}
    for i, (_name, amount, _pct) in enumerate(body):
        s = 0.0
        for j in range(i + 1, n):
            cj = body[j][1]
            if cj is None:
                break
            s += cj
            if abs(s - amount) <= max(1.0, abs(amount) * 1e-6):
                is_header[i] = True
                for k in range(i + 1, j + 1):
                    child_parent[k] = i
                break
            if s > amount + 1.0:
                break

    holdings: List[Holding] = []
    for i, (name, amount, pct) in enumerate(body):
        parent = child_parent.get(i)
        sub_sector = body[parent][0] if parent is not None else (name if is_header[i] else None)
        holdings.append(Holding(
            sub_sector=sub_sector, issuer=name, issuer_slug=issuer_slug(name),
            amount=amount, pct=pct, is_subtotal=is_header[i],
            macro_class=None if is_header[i] else _macro_class(name),
        ))

    leaves = sum(h.amount for h in holdings if not h.is_subtotal and h.amount is not None)
    if abs(leaves - total) > total * _RECONCILE_TOL:
        raise CarteraExtractionError(
            f"Cuadro 6.1 no cuadra: Σ emisores {leaves:,.2f} vs TOTAL {total:,.2f}"
        )
    return holdings


def extract_cartera_from_pdf(content: bytes) -> Tuple[str, List[Holding]]:  # pragma: no cover - pdf I/O
    """``(period, holdings)`` from a bulletin PDF: find the Cuadro 6.1 page, parse it."""
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "cartera de inversiones de los fondos de pensiones por emisor" in text.lower():
                period = cartera_period(text)
                holdings = parse_cartera_words(page.extract_words())
                if not period:
                    raise CarteraExtractionError("Cuadro 6.1: no se determinó el período")
                return period, holdings
    raise CarteraExtractionError("No se encontró el Cuadro 6.1 en el boletín")
