"""Extract the pension funds' unit value (valor cuota / NAV) from the SIPEN bulletin.

Source: *Cuadro 6.4 — Valor cuota de los fondos de pensiones (RD$), según entidad* in the
quarterly Boletín Trimestral (PDF). Unlike the return series in the Estadística Previsional
XLSX (which is a **trailing-12m annualized** figure — smoothed, useless for volatility), the
valor cuota is the funds' cumulative unit value (base 100 at 2003), published **monthly per
AFP**. Chaining consecutive bulletins yields a true monthly NAV series → real monthly
returns → realized volatility (the ISA *riesgo* dimension, decision 2026-07-01).

Approach (verified 2026-07-01): the bulletin's text layer (via ``pdfminer.high_level`` —
ships with the ``pdfplumber`` dependency) renders each statistical table as a
``Fondo<Month><Month><Month>`` header followed by ``<AFP> <v1> <v2> <v3>`` rows. Several
tables share that header (valor cuota 6.4, nominal return 6.5, real return 6.6), so the NAV
grid is disambiguated **by magnitude**: valor cuota levels are hundreds-to-thousands (base
100, 20+ years of compounding), while the return grids are single-digit percents. The
reporting year comes from the ``Trimestre … de YYYY`` caption (NOT the "base 100 al … 2003"
footnote — that mismatch silently injected 2003 points in an early draft). Non-AFP funds
(Banco Central, Banco de Reservas, INABIMA, …) are skipped by mapping only the seven live
AFP labels. Missing/garbled → the fund is absent, never an invented NAV.
"""
from __future__ import annotations

import io
import re
from typing import Dict, List, Optional, Tuple

# Cuadro 6.4 AFP label → PensionEntity slug (the seven live AFPs; non-AFP funds skipped).
_AFP_BY_LABEL: Dict[str, str] = {
    "Atlántico": "afp_atlantico",
    "Crecer": "afp_crecer",
    "JMMB-BDI": "afp_jmmb_bdi",
    "Popular": "afp_popular",
    "Reservas": "afp_reservas",
    "Romana": "afp_romana",
    "Siembra": "afp_siembra",
}
_MONTH_NAMES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
                "Septiembre", "Octubre", "Noviembre", "Diciembre"]
_MIDX = {m: i + 1 for i, m in enumerate(_MONTH_NAMES)}
_MRE = "|".join(_MONTH_NAMES)
# NAV levels are ≥100 (base 100, 20+y compounding); return grids are single-digit %.
_NAV_MIN_LEVEL = 100.0


def _quarter_year(text: str) -> Optional[int]:
    """Reporting year from the valor-cuota caption ``Trimestre <m> - <m> [de] YYYY``. Anchors
    on the caption so it never picks up the "base 100 al 1 de … de 2003" footnote year."""
    m = re.search(
        r"valor cuota de los fondos de pensiones.*?trimestre\s+(?:%s)\s*-\s*(?:%s)\s+(?:de\s+)?(\d{4})"
        % (_MRE, _MRE), text, re.IGNORECASE | re.DOTALL)
    return int(m.group(1)) if m else None


def _parse_grid_rows(span: str, months: List[str]) -> Dict[str, List[float]]:
    """For each AFP label, the ≤3 numeric values that follow it in *span*."""
    out: Dict[str, List[float]] = {}
    for label, slug in _AFP_BY_LABEL.items():
        m = re.search(re.escape(label) + r"\s+([\d.,]+)(?:\s+([\d.,]+))?(?:\s+([\d.,]+))?", span)
        if m:
            nums = [float(x.replace(",", "")) for x in m.groups() if x]
            out[slug] = nums[:len(months)]
    return out


def parse_valor_cuota_text(text: str) -> Dict[str, List[Tuple[str, float]]]:
    """Parse a bulletin's text → ``{afp_slug: [(period 'YYYY-MM', nav), …]}`` for the NAV
    (Cuadro 6.4) grid only. Pure (no I/O) — the unit under test. Returns ``{}`` if the year
    or the NAV grid can't be located (never guesses)."""
    year = _quarter_year(text)
    if not year:
        return {}
    for gm in re.finditer(r"Fondo\s*((?:(?:%s)\s*){1,3})" % _MRE, text):
        months = re.findall(_MRE, gm.group(1))
        vals = _parse_grid_rows(text[gm.end():gm.end() + 900], months)
        levels = [v for arr in vals.values() for v in arr]
        # Disambiguate the NAV grid from the return grids by magnitude.
        if len(vals) >= 5 and levels and max(levels) > _NAV_MIN_LEVEL:
            out: Dict[str, List[Tuple[str, float]]] = {}
            for slug, arr in vals.items():
                pts = [(f"{year}-{_MIDX[months[k]]:02d}", v)
                       for k, v in enumerate(arr) if k < len(months)]
                if pts:
                    out[slug] = pts
            return out
    return {}


def extract_valor_cuota_from_pdf(content: bytes) -> Dict[str, List[Tuple[str, float]]]:
    """Extract the NAV (Cuadro 6.4) from one bulletin PDF → ``{afp_slug: [(period, nav)]}``.

    Uses the PDF text layer (``pdfminer.high_level.extract_text``, a ``pdfplumber``
    dependency). Best-effort: unreadable PDF → ``{}``."""
    from pdfminer.high_level import extract_text

    try:
        text = extract_text(io.BytesIO(content))
    except Exception:  # noqa: BLE001 — unreadable → caller keeps prior data
        return {}
    return parse_valor_cuota_text(text)
