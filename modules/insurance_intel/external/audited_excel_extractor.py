"""Extract insurer financials from the SIS audited-statements Excel (por cía).

Source: ``Estados-Financieros-Auditados-por-cia-<year>.xlsx`` (SIS transparencia),
one **sheet per insurer**, each a regulatory chart of accounts:
``[CTAS, DESCRIPCION, <year>, <year-1>]``. Sections by 1-digit code:
``1 ACTIVO · 2 PASIVO · 3 CAPITAL/PATRIMONIO · 4 INGRESOS · 5 GASTOS``.

Deterministic, reconciled parse — NO OCR (the file is clean Excel):
  * Balance-sheet totals = sum of the 4-digit **leaf** accounts under each section
    (contra-accounts are already negative). Reconciled: |activo − pasivo −
    patrimonio| / activo must be < 1% or the sheet is flagged (fail-soft: returned
    with ``reconciled=False``, never silently trusted).
  * Income statement uses 6-digit per-ramo leaves under 4-digit sub-headers:
      - primas suscritas (direct) = Σ children of sub-headers "PRIMAS SUSCRITAS"
      - siniestros pagados = Σ children of "RECLAMACIONES PAGADAS POR SINIESTRO"
  * Liquidity inputs: inversiones (11xx) + efectivo (12xx); reservas técnicas
    (21xx + 22xx).

Missing values stay ``None`` — never interpolated.
"""
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.insurance_intel.audited")


@dataclass
class InsurerFinancials:
    name: str
    slug: str
    period: str                 # the year, "2024"
    activos: Optional[float]
    pasivos: Optional[float]
    patrimonio: Optional[float]
    reservas_tecnicas: Optional[float]
    activos_liquidos: Optional[float]
    primas: Optional[float]      # primas suscritas directas
    siniestros: Optional[float]  # reclamaciones pagadas por siniestro (directo)
    ingresos: Optional[float]
    gastos: Optional[float]
    reconciled: bool

    def as_series(self) -> Dict[str, Optional[float]]:
        """The per-insurer series persisted to ``insurance_series`` (entity_slug set)."""
        return {
            "activos_totales": self.activos,
            "pasivos_totales": self.pasivos,
            "patrimonio": self.patrimonio,
            "reservas_tecnicas": self.reservas_tecnicas,
            "activos_liquidos": self.activos_liquidos,
            "primas_suscritas": self.primas,
            "siniestros_pagados": self.siniestros,
            "ingresos_totales": self.ingresos,
            "gastos_totales": self.gastos,
        }


def slugify_insurer(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\b(s\.?\s?a\.?|c\.?\s?por\.?\s?a\.?|comp(a|añia|ania)?|de seguros|seguros)\b",
               " ", s, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "aseguradora"


def _to_num(v) -> Optional[float]:
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _extract_sheet(rows: List[tuple], name: str, period: str) -> Optional[InsurerFinancials]:
    """Extract one insurer sheet from ``[(cta, desc, cur), ...]``. None if not a
    financial-statement sheet (no ACTIVO section)."""
    cta = {}       # code -> value (leaf)
    desc_by_code = {}
    codes_present = set()
    for c, d, v in rows:
        c = str(c).strip()
        codes_present.add(c)
        desc_by_code[c] = str(d).strip().upper()
        n = _to_num(v)
        if n is not None:
            cta[c] = n

    if "1" not in codes_present or "3" not in codes_present:
        return None  # not a statement sheet

    def leaves_sum(prefix: str, ndig: int = 4) -> Optional[float]:
        vals = [v for c, v in cta.items()
                if len(c) == ndig and c.isdigit() and c.startswith(prefix)]
        return round(sum(vals), 2) if vals else None

    def children_sum_where(desc_kw: str) -> Optional[float]:
        """Σ of 6-digit leaves under any 4-digit sub-header whose desc contains kw."""
        heads = [c for c in codes_present
                 if len(c) == 4 and c.isdigit() and desc_kw in desc_by_code.get(c, "")]
        total, seen = 0.0, False
        for h in heads:
            for c, v in cta.items():
                if len(c) == 6 and c.isdigit() and c.startswith(h):
                    total += v
                    seen = True
        return round(total, 2) if seen else None

    activos = leaves_sum("1")
    pasivos = leaves_sum("2")
    patrimonio = leaves_sum("3")
    reservas = None
    r21, r22 = leaves_sum("21"), leaves_sum("22")
    if r21 is not None or r22 is not None:
        reservas = round((r21 or 0) + (r22 or 0), 2)
    liq = None
    inv, efe = leaves_sum("11"), leaves_sum("12")
    if inv is not None or efe is not None:
        liq = round((inv or 0) + (efe or 0), 2)

    # Income statement: 6-digit leaves under 4/5 sub-headers → total ingresos/gastos.
    ingresos = leaves_sum("4", ndig=6)
    gastos = leaves_sum("5", ndig=6)
    primas = children_sum_where("PRIMAS SUSCRITAS")
    siniestros = children_sum_where("RECLAMACIONES PAGADAS POR SINIESTRO")

    reconciled = bool(
        activos and pasivos is not None and patrimonio is not None
        and abs(activos - pasivos - patrimonio) / activos < 0.01
    )
    if not reconciled:
        logger.warning("Balance no cuadra para '%s' (%s): A=%s P=%s Pat=%s",
                       name, period, activos, pasivos, patrimonio)

    return InsurerFinancials(
        name=name.strip(), slug=slugify_insurer(name), period=period,
        activos=activos, pasivos=pasivos, patrimonio=patrimonio,
        reservas_tecnicas=reservas, activos_liquidos=liq,
        primas=primas, siniestros=siniestros, ingresos=ingresos, gastos=gastos,
        reconciled=reconciled)


def extract_audited_workbook(content: bytes, period: str) -> List[InsurerFinancials]:
    """Extract every insurer sheet from an audited-statements workbook (bytes)."""
    import pandas as pd

    xl = pd.ExcelFile(io.BytesIO(content))
    out: List[InsurerFinancials] = []
    for sheet in xl.sheet_names:
        try:
            df = pd.read_excel(xl, sheet_name=sheet, header=None)
            if df.shape[1] < 3:
                continue  # index/cover sheet, not a 3-column statement
            rows = [(r[0], r[1], r[2]) for r in df.itertuples(index=False, name=None)]
            fin = _extract_sheet(rows, sheet, period)
        except Exception as e:  # noqa: BLE001 — one bad sheet never sinks the workbook
            logger.warning("Hoja '%s' no extraída: %s", sheet, e)
            fin = None
        if fin is not None:
            out.append(fin)
    return out


def to_dict(fins: List[InsurerFinancials]) -> List[Dict]:
    return [asdict(f) for f in fins]
