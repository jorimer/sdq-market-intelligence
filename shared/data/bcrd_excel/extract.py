"""Apply an :class:`ExtractionSpec` to a workbook → normalized ``Record``s.

This layer is purely deterministic: given a (correct) spec it always produces the
same records, so it is exhaustively unit-tested against the three calibration
files. All the heterogeneity lives upstream in the spec; here we only replay it.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from shared.data.base_client import Record
from shared.data.lineage import Lineage

from .periods import (
    coerce_num,
    format_period,
    normalize_label,
    parse_month,
    parse_quarter,
    parse_year,
)
from .spec import ExtractionSpec
from .workbook import Grid, Workbook

_LICENSE = "datos oficiales BCRD — uso público con cita"


_FOOTNOTE_RE = re.compile(r"\s*\d+\s*/")  # BCRD footnote markers: "BRUTAS 1/", "2008 3/"


def _clean_label(s: str) -> str:
    """Drop footnote markers so ``"BRUTAS 1/"`` and ``"BRUTAS"`` slug the same."""
    return _FOOTNOTE_RE.sub(" ", normalize_label(s)).strip()


def _slug(s: str) -> str:
    out = []
    for ch in _clean_label(s):
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "x"


def _code_prefix(spec: ExtractionSpec) -> str:
    if spec.code_prefix:
        return spec.code_prefix
    stem = Path(spec.file).stem.split(".")[0]
    return f"bcrd.xls.{_slug(stem)}"


def _lineage(spec: ExtractionSpec) -> Lineage:
    url = spec.file if str(spec.file).startswith("http") else None
    return Lineage(source="BCRD", license=_LICENSE, fetched_at=date.today(), url=url)


def _forward_filled_years(grid: Grid, row: int, c0: int, c1: int) -> Dict[int, int]:
    """``col → year`` across [c0, c1), forward-filling sparse year headers."""
    col_year: Dict[int, int] = {}
    current: Optional[int] = None
    for c in range(c0, c1):
        y = parse_year(grid.cell(row, c))
        if y is not None:
            current = y
        if current is not None:
            col_year[c] = current
    return col_year


def _extract_period_rows(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                         prefix: str) -> List[Record]:
    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    series = spec.series
    subtotal_re = re.compile(spec.subtotal_year_regex) if spec.subtotal_year_regex else None
    out: List[Record] = []

    def emit(year: int, month: Optional[int], r: int) -> None:
        period = format_period(year, month)
        for s in series:
            out.append(Record(
                series=f"{prefix}.{s.code}" if not s.code.startswith(prefix) else s.code,
                period=period, value=coerce_num(grid.cell(r, s.value_col)),
                lineage=lineage, unit=s.unit,
            ))

    if subtotal_re is not None:
        # Year revealed by a trailing subtotal row ("Promedio 2007"); buffer the
        # block's months and stamp them once the year appears.
        buffer: List[tuple[int, int]] = []  # (row, month)
        last_year: Optional[int] = None
        for r in range(spec.data_row_start, end):
            label = " ".join(
                normalize_label(grid.cell(r, c)) for c in range(0, (spec.month_col or 0) + 2)
            )
            m = subtotal_re.search(label)
            if m:
                year = int(m.group(1))
                for br, bmonth in buffer:
                    emit(year, bmonth, br)
                last_year = year
                buffer = []
                continue
            month = parse_month(grid.cell(r, spec.month_col)) if spec.month_col is not None else None
            if month is not None:
                buffer.append((r, month))
        # A still-open final block (latest year, no subtotal yet): infer +1.
        if buffer and last_year is not None and len(buffer) <= 12:
            for br, bmonth in buffer:
                emit(last_year + 1, bmonth, br)
        return out

    # Sparse year column, forward-filled down the rows. With no month column this
    # is the *annual* case: each row that carries its own year is one obs.
    annual = spec.month_col is None
    current_year: Optional[int] = None
    for r in range(spec.data_row_start, end):
        row_year = parse_year(grid.cell(r, spec.year_col)) if spec.year_col is not None else None
        if row_year is not None:
            current_year = row_year
        if annual:
            if row_year is None:  # header / blank / sub-total row → skip
                continue
            emit(row_year, None, r)
            continue
        month = parse_month(grid.cell(r, spec.month_col))
        if month is None or current_year is None:
            continue
        emit(current_year, month, r)
    return out


def _extract_matrix(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                    prefix: str) -> List[Record]:
    """Transpose of period_rows: periods across a header row, series down the rows."""
    c0 = spec.value_col_start or 0
    c1 = spec.value_col_end if spec.value_col_end is not None else grid.ncols
    label_col = spec.label_col if spec.label_col is not None else 0
    col_year = _forward_filled_years(grid, spec.period_header_row, c0, c1)
    # Optional sub-period row: quarter or month per column.
    col_sub: Dict[int, tuple] = {}
    if spec.subperiod_header_row is not None:
        for c in range(c0, c1):
            cell = grid.cell(spec.subperiod_header_row, c)
            q = parse_quarter(cell)
            if q is not None:
                col_sub[c] = ("Q", q)
                continue
            m = parse_month(cell)
            if m is not None:
                col_sub[c] = ("M", m)

    def period_for(year: int, c: int) -> str:
        sub = col_sub.get(c)
        if sub and sub[0] == "Q":
            return format_period(year, None, sub[1])
        if sub and sub[0] == "M":
            return format_period(year, sub[1])
        return format_period(year, None)

    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    out: List[Record] = []
    seen: Dict[str, int] = {}
    for r in range(spec.data_row_start, end):
        raw = grid.cell(r, label_col)
        if raw is None or isinstance(raw, (int, float)):
            continue
        name = str(raw).strip()
        if not name:
            continue
        # Skip pure section headers: rows with no numeric value in the grid.
        if not any(isinstance(grid.cell(r, c), (int, float)) for c in range(c0, c1)):
            continue
        code = _slug(name)
        if code in seen:  # two rows reusing a label → keep them distinct, never merge
            code = f"{code}_r{r}"
        seen[code] = r
        for c in range(c0, c1):
            year = col_year.get(c)
            if year is None:
                continue
            out.append(Record(
                series=f"{prefix}.{code}", period=period_for(year, c),
                value=coerce_num(grid.cell(r, c)), lineage=lineage, unit=spec.unit,
            ))
    return out


def _extract_cross_tab(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                       prefix: str) -> List[Record]:
    c0 = spec.value_col_start or 0
    c1 = spec.value_col_end if spec.value_col_end is not None else grid.ncols
    col_year = _forward_filled_years(grid, spec.year_header_row, c0, c1)
    # Forward-fill the optional super-header (ACTIVOS/RESERVAS) across the value
    # range; columns before any super-label (the pre-methodology block) get none.
    col_super: Dict[int, str] = {}
    if spec.super_header_row is not None:
        current = ""
        for c in range(c0, c1):
            lab = _clean_label(grid.cell(spec.super_header_row, c))
            if lab:
                current = lab
            if current:
                col_super[c] = current
    col_metric: Dict[int, str] = {}
    if spec.metric_header_row is not None:
        for c in range(c0, c1):
            label = _clean_label(grid.cell(spec.metric_header_row, c))
            if label:
                sup = col_super.get(c, "")
                col_metric[c] = f"{sup} {label}".strip() if sup else label
    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    out: List[Record] = []
    for r in range(spec.data_row_start, end):
        month = parse_month(grid.cell(r, spec.month_col)) if spec.month_col is not None else None
        if month is None:
            continue
        for c in range(c0, c1):
            year = col_year.get(c)
            if year is None:
                continue
            metric = col_metric.get(c, "valor")
            code = f"{prefix}.{_slug(metric)}"
            out.append(Record(
                series=code, period=format_period(year, month),
                value=coerce_num(grid.cell(r, c)), lineage=lineage, unit=spec.unit,
            ))
    return out


def extract_records(workbook: Workbook, spec: ExtractionSpec) -> List[Record]:
    """Replay *spec* over *workbook* → ``Record``s (one per series × period)."""
    grid = workbook.grid(spec.sheet)
    lineage = _lineage(spec)
    prefix = _code_prefix(spec)
    if spec.orientation == "cross_tab":
        return _extract_cross_tab(grid, spec, lineage, prefix)
    if spec.orientation == "matrix":
        return _extract_matrix(grid, spec, lineage, prefix)
    return _extract_period_rows(grid, spec, lineage, prefix)
