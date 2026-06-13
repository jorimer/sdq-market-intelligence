"""``ExtractionSpec`` — the cached, serializable recipe to read one BCRD Excel.

A spec is produced once per file (by the heuristic or by Claude), cached by the
workbook's ``structure_hash``, and replayed by :mod:`extract` on every refresh.
It is deliberately declarative (no code) so it can round-trip through JSON and be
emitted directly by the Claude interpreter.

Two orientations cover the corpus:

* ``period_rows`` — one period per data row. The month sits in ``month_col``; the
  year is resolved by one of two strategies:
    - ``year_col`` set → sparse year column, forward-filled (e.g. IPC).
    - ``subtotal_year_regex`` set → the year is only revealed by a trailing
      subtotal row such as ``"Promedio 2007"`` that closes each 12-month block
      (e.g. IMAE). Buffered months inherit that year.
  Each :class:`SeriesSpec` names a value column.

* ``cross_tab`` — periods on both axes: years across a header row (sparse,
  forward-filled) and months down ``month_col``; metrics (e.g. BRUTAS/NETAS)
  repeat across columns. Series are synthesized per (metric × value column).

* ``matrix`` — the transpose of ``period_rows``: periods run *across* a header
  row (years in ``period_header_row``, optionally a quarter/month sub-row), and
  each *data row* is a series whose name sits in ``label_col`` (e.g. national
  accounts: concepts down the rows, years across the columns).

A series period may be monthly (``YYYY-MM``), quarterly (``YYYY-Qn``) or annual
(``YYYY``); ``period_rows`` with ``month_col=None`` is the annual case.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

ORIENTATIONS = ("period_rows", "cross_tab", "matrix")


@dataclass
class SeriesSpec:
    """One output series anchored to a value column (``period_rows``)."""

    code: str
    name: str
    unit: Optional[str]
    value_col: int


@dataclass
class ExtractionSpec:
    file: str
    sheet: str
    orientation: str
    data_row_start: int
    data_row_end: Optional[int] = None

    # ── period_rows ──────────────────────────────────────────────
    month_col: Optional[int] = None
    year_col: Optional[int] = None
    subtotal_year_regex: Optional[str] = None
    series: List[SeriesSpec] = field(default_factory=list)

    # ── cross_tab ────────────────────────────────────────────────
    year_header_row: Optional[int] = None
    metric_header_row: Optional[int] = None
    # Optional super-header above the metric row (e.g. ACTIVOS / RESERVAS), sparse
    # and forward-filled; concatenated before the metric to disambiguate series
    # that reuse a label across a methodology change.
    super_header_row: Optional[int] = None
    value_col_start: Optional[int] = None
    value_col_end: Optional[int] = None
    code_prefix: str = ""
    unit: Optional[str] = None

    # ── matrix (periods across columns, series down rows) ────────
    period_header_row: Optional[int] = None       # row of years across columns
    subperiod_header_row: Optional[int] = None     # row of quarters/months (optional)
    label_col: Optional[int] = None                # column holding each row's series name
    frequency: Optional[str] = None                # "annual" | "quarterly" | "monthly"

    # ── provenance / caching ─────────────────────────────────────
    structure_hash: str = ""
    confidence: float = 0.0
    method: str = "heuristic"  # heuristic | claude | cached | manual
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractionSpec":
        d = dict(d)
        d["series"] = [SeriesSpec(**s) for s in d.get("series", [])]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})
