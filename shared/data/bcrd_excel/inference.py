"""Heuristic structural inference — grid → :class:`ExtractionSpec` + confidence.

This resolves the common BCRD layouts without a model call. It scores its own
output; the engine routes anything below a confidence threshold to the Claude
interpreter. The signals it reads:

* the **month axis** — the column (period_rows) or row-region with the densest run
  of Spanish month names;
* the **year strategy** — a sparse year column aligned to the data rows, or
  trailing ``"Promedio YYYY"`` subtotal rows that close each block;
* **cross-tab** — a header row carrying many years spread across columns while a
  column carries months (periods on both axes);
* **value columns** — numeric-dense columns, named from the header rows above.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .periods import normalize_label, parse_month, parse_year
from .spec import ExtractionSpec, SeriesSpec
from .workbook import Grid, Workbook

_SUBTOTAL_RE = r"promedio\s+(\d{4})"
_SCAN_HEADER_ROWS = 12  # header region to mine for names / year rows


def _pick_sheet(wb: Workbook) -> Grid:
    """The sheet with the most numeric cells (the data sheet, not notes/cover)."""
    best, best_score = wb.grids[0], -1.0
    for g in wb.grids:
        n = sum(
            1
            for r in range(min(60, g.nrows))
            for c in range(min(40, g.ncols))
            if isinstance(g.cell(r, c), (int, float))
        )
        if n > best_score:
            best, best_score = g, n
    return best


def _month_column(grid: Grid) -> Tuple[Optional[int], int, int]:
    """Find the column richest in month names. Returns (col, first_row, count)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(6, grid.ncols)):
        rows = [r for r in range(grid.nrows) if parse_month(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_first, best_count


def _year_header_row(grid: Grid) -> Tuple[Optional[int], int]:
    """Find a header row carrying several years across columns (cross-tab)."""
    best_row, best_count = None, 0
    for r in range(min(_SCAN_HEADER_ROWS, grid.nrows)):
        years = sum(
            1 for c in range(grid.ncols) if parse_year(grid.cell(r, c)) is not None
        )
        if years > best_count:
            best_row, best_count = r, years
    return best_row, best_count


def _has_subtotal_years(grid: Grid, month_col: int) -> bool:
    rx = re.compile(_SUBTOTAL_RE)
    for r in range(grid.nrows):
        label = " ".join(normalize_label(grid.cell(r, c)) for c in range(0, month_col + 2))
        if rx.search(label):
            return True
    return False


def _sparse_year_column(grid: Grid, month_col: int, row0: int) -> Optional[int]:
    """A column (left of months) with parseable years on some data rows."""
    for c in range(0, month_col + 1):
        hits = sum(
            1 for r in range(row0, min(row0 + 60, grid.nrows))
            if parse_year(grid.cell(r, c)) is not None
        )
        if hits >= 1:
            return c
    return None


def _header_name(grid: Grid, value_col: int, data_row0: int) -> str:
    """Build a series name from the non-empty header cells above a value column."""
    parts: List[str] = []
    for r in range(max(0, data_row0 - 6), data_row0):
        for c in (value_col, value_col - 1):  # headers sometimes sit one col left
            v = grid.cell(r, c)
            if v is not None and not isinstance(v, (int, float)):
                txt = str(v).strip()
                if txt and txt.lower() not in (p.lower() for p in parts):
                    parts.append(txt)
                break
    return " · ".join(parts[-3:]) or f"col{value_col}"


def _value_columns(grid: Grid, month_col: int, data_row0: int) -> List[int]:
    """Columns after the month column that are numeric-dense over the data rows."""
    cols: List[int] = []
    sample_end = min(data_row0 + 80, grid.nrows)
    span = max(1, sample_end - data_row0)
    for c in range(month_col + 1, grid.ncols):
        numeric = sum(
            1 for r in range(data_row0, sample_end)
            if isinstance(grid.cell(r, c), (int, float))
        )
        if numeric / span >= 0.4:
            cols.append(c)
    return cols


def _slug(s: str) -> str:
    out = [ch if ch.isalnum() else "_" for ch in normalize_label(s)]
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "x"


def infer_spec(wb: Workbook, file: str) -> ExtractionSpec:
    """Infer an :class:`ExtractionSpec` for *wb*, scoring its own confidence."""
    grid = _pick_sheet(wb)
    month_col, first_month_row, month_count = _month_column(grid)
    year_row, year_row_count = _year_header_row(grid)
    sh = wb.structure_hash()

    # Cross-tab: many years across a header row AND months down a column.
    if year_row_count >= 4 and month_col is not None and month_count >= 6:
        # value columns start just after the month column
        c0 = month_col + 1
        years_on_row = [c for c in range(c0, grid.ncols)
                        if parse_year(grid.cell(year_row, c)) is not None]
        c1 = (max(years_on_row) + 3) if years_on_row else grid.ncols
        # The metric row is the last header row just above the first data row.
        metric_row = max(year_row + 1, first_month_row - 1)
        # A super-header sits between the years and the metrics when that gap has
        # sparse text labels (e.g. ACTIVOS / RESERVAS over BRUTOS / BRUTAS / NETAS).
        super_row = None
        for r in range(year_row + 1, metric_row):
            texts = sum(1 for c in range(c0, c1)
                        if isinstance(grid.cell(r, c), str) and grid.cell(r, c).strip())
            if texts >= 2:
                super_row = r
                break
        conf = min(0.9, 0.5 + 0.05 * year_row_count)
        return ExtractionSpec(
            file=file, sheet=grid.name, orientation="cross_tab",
            data_row_start=first_month_row, month_col=month_col,
            year_header_row=year_row, metric_header_row=metric_row,
            super_header_row=super_row,
            value_col_start=c0, value_col_end=c1,
            structure_hash=sh, confidence=round(conf, 2), method="heuristic",
            notes=f"cross_tab: {year_row_count} años en fila {year_row}",
        )

    # period_rows
    if month_col is not None and month_count >= 6:
        subtotal = _has_subtotal_years(grid, month_col)
        year_col = None if subtotal else _sparse_year_column(grid, month_col, first_month_row)
        value_cols = _value_columns(grid, month_col, first_month_row)
        series = [
            SeriesSpec(code=_slug(_header_name(grid, c, first_month_row)),
                       name=_header_name(grid, c, first_month_row),
                       unit=None, value_col=c)
            for c in value_cols
        ]
        resolved = subtotal or year_col is not None
        conf = min(0.85, 0.5 + 0.03 * month_count) if (resolved and series) else 0.0
        return ExtractionSpec(
            file=file, sheet=grid.name, orientation="period_rows",
            data_row_start=first_month_row, month_col=month_col, year_col=year_col,
            subtotal_year_regex=_SUBTOTAL_RE if subtotal else None,
            series=series, structure_hash=sh,
            confidence=round(conf, 2) if resolved else 0.2,
            method="heuristic",
            notes=("subtotal-year" if subtotal else f"year_col={year_col}"),
        )

    # Unresolved — let the interpreter take it.
    return ExtractionSpec(
        file=file, sheet=grid.name, orientation="period_rows",
        data_row_start=0, structure_hash=sh, confidence=0.0, method="heuristic",
        notes="sin eje de período detectado",
    )
