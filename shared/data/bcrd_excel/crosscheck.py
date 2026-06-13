"""Cross-validate the Excel-extracted series against the live BCRD API series.

The single strongest proof of correctness: the figures the engine pulls out of the
historical Excel must equal the figures the BCRD API reports for the same months.
Some quantities compare directly (reserves, exchange rates — same unit); the price
index does NOT (the Excel is base 1999, the API index a later base), so for the
CPI we compare *year-over-year inflation*, which is base-invariant.

This module is pure (no DB / network): it defines the curated mapping, the YoY
transform and the period-by-period comparison. The DB/engine wiring lives in
``macro_monitor.service``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CrossCheckSpec:
    """One curated cross-check: an extracted Excel series vs a canonical API series."""

    label: str
    excel_key: str               # catalog filename to extract
    excel_series_suffix: str     # which extracted series (``series_code`` endswith)
    api_series: str              # canonical MacroSeries code to compare against
    transform: str = "identity"  # "identity" | "yoy"
    rel_tol: float = 0.02        # relative tolerance for level series
    abs_tol: float = 0.0         # absolute tolerance (e.g. pp for inflation)
    note: str = ""


# The overlap that actually exists today: IPC has deep history (YoY); reserves /
# IMAE are API-snapshot (one month) so they are point checks; FX is deep but a
# slightly different concept (reference rate) — its match rate is informative.
CROSSCHECK_SPECS: List[CrossCheckSpec] = [
    CrossCheckSpec(
        label="Inflación interanual (IPC)", excel_key="ipc.xls",
        excel_series_suffix="indice_base_1999",
        api_series="bcrd.inflacion.inflacion.interanual",
        transform="yoy", abs_tol=0.15,
        note="IPC base 1999 → YoY (invariante a la base) vs inflación interanual del API",
    ),
    CrossCheckSpec(
        label="Reservas internacionales brutas", excel_key="reservas_internacionales.xlsx",
        excel_series_suffix=".reservas_brutas",
        api_series="bcrd.sector_externo.reservas_internacionales.brutas",
        transform="identity", rel_tol=0.02,
        note="US$ MM, metodología 2003+ (RESERVAS BRUTAS)",
    ),
    CrossCheckSpec(
        label="Reservas internacionales netas", excel_key="reservas_internacionales.xlsx",
        excel_series_suffix=".reservas_netas",
        api_series="bcrd.sector_externo.reservas_internacionales.netas",
        transform="identity", rel_tol=0.02,
    ),
]


def yoy(series: Dict[str, Optional[float]]) -> Dict[str, float]:
    """Year-over-year % change for a monthly ``{"YYYY-MM": value}`` series."""
    clean = {p: v for p, v in series.items() if v is not None}
    out: Dict[str, float] = {}
    for period, value in clean.items():
        try:
            year, month = period.split("-")
        except ValueError:
            continue
        prev = f"{int(year) - 1}-{month}"
        base = clean.get(prev)
        if base:
            out[period] = round((value / base - 1) * 100, 2)
    return out


@dataclass
class CompareResult:
    n_compared: int = 0
    n_match: int = 0
    n_mismatch: int = 0
    max_abs_err: float = 0.0
    period_min: Optional[str] = None
    period_max: Optional[str] = None
    examples: List[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.n_compared > 0 and self.n_mismatch == 0


def compare(
    excel_vals: Dict[str, Optional[float]],
    api_vals: Dict[str, Optional[float]],
    *, rel_tol: float, abs_tol: float,
) -> CompareResult:
    """Compare two ``{period: value}`` maps over their overlapping periods.

    A point matches when ``|excel - api| <= abs_tol`` OR the relative error
    ``<= rel_tol`` (so both level series and pp-quantities are handled).
    """
    res = CompareResult()
    common = sorted(set(excel_vals) & set(api_vals))
    for period in common:
        e, a = excel_vals.get(period), api_vals.get(period)
        if e is None or a is None:
            continue
        res.n_compared += 1
        res.period_min = res.period_min or period
        res.period_max = period
        abs_err = abs(e - a)
        rel_err = abs_err / max(abs(a), 1e-9)
        res.max_abs_err = max(res.max_abs_err, round(abs_err, 4))
        if abs_err <= abs_tol or rel_err <= rel_tol:
            res.n_match += 1
        else:
            res.n_mismatch += 1
            if len(res.examples) < 5:
                res.examples.append({"period": period, "excel": round(e, 4),
                                     "api": round(a, 4), "abs_err": round(abs_err, 4)})
    return res
