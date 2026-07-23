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

from .periods import normalize_label, parse_month, parse_quarter, parse_year
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


def _axis_year(value) -> Optional[int]:
    """Years for *axis detection* — stricter than ``parse_year`` so a year buried in
    a subtitle ("Bases 1999 y 2010") or a range ("1991-2013") is NOT counted as a
    period axis. Accepts a numeric year cell, or a string that *is* a year (allowing
    a trailing footnote like "2008 3/")."""
    if isinstance(value, (int, float)):
        y = int(value)
        return y if 1900 <= y <= 2100 else None
    token = normalize_label(value)
    token = re.sub(r"\s*\d+\s*/", "", token).strip()  # drop "3/" footnotes
    if re.fullmatch(r"(19|20)\d{2}", token):
        return int(token)
    return None


def _row_is_mostly_numeric(grid: Grid, row: int, c0: int, c1: int) -> bool:
    """¿La fila trae mayoría de números? Entonces son DATOS, no rótulos.

    Un encabezado nombra; una fila de datos mide. Si se confunden, las series terminan
    llamándose como el valor de una celda — y el error no se ve en la extracción, se ve
    meses después cuando un informe cita `serie.280155040_6400002`."""
    filled = numeric = 0
    for c in range(c0, c1):
        cell = grid.cell(row, c)
        if cell in (None, ""):
            continue
        filled += 1
        if isinstance(cell, (int, float)):
            numeric += 1
        else:
            try:
                float(str(cell).replace(",", "").strip())
                numeric += 1
            except ValueError:
                pass
    return filled > 0 and numeric / filled > 0.5


def _year_header_row(grid: Grid) -> Tuple[Optional[int], int]:
    """Find a header row carrying several years across columns (cross-tab / matrix)."""
    best_row, best_count = None, 0
    for r in range(min(_SCAN_HEADER_ROWS, grid.nrows)):
        years = sum(1 for c in range(grid.ncols) if _axis_year(grid.cell(r, c)) is not None)
        if years > best_count:
            best_row, best_count = r, years
    return best_row, best_count


def _quarter_column(grid: Grid) -> Tuple[Optional[int], int, int]:
    """Column richest in quarter labels (I-IV / E-M / T1-T4). (col, first_row, count)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(4, grid.ncols)):
        rows = [r for r in range(grid.nrows) if parse_quarter(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_first, best_count


def _has_year_markers(grid: Grid, col: int) -> bool:
    """True if year-marker rows exist in *col*: 'Promedio YYYY' or a bare year."""
    rx = re.compile(_SUBTOTAL_RE)
    for r in range(grid.nrows):
        label = " ".join(normalize_label(grid.cell(r, c)) for c in range(0, col + 2))
        if rx.search(label):
            return True
        cell = grid.cell(r, col)
        if parse_quarter(cell) is None and parse_month(cell) is None:
            v = cell if isinstance(cell, (int, float)) else None
            if v is not None and 1900 <= int(v) <= 2100:
                return True
    return False


def _year_column(grid: Grid) -> tuple[Optional[int], int, int]:
    """Column richest in years *down the rows* (annual period_rows). (col, count, first_row)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(4, grid.ncols)):
        rows = [r for r in range(grid.nrows) if _axis_year(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_count, best_first


def _label_column(grid: Grid, value_col_start: int, row0: int, row1: int) -> Optional[int]:
    """Column left of the values richest in text labels (the series names, matrix)."""
    best_col, best_count = None, 0
    for c in range(0, max(1, value_col_start)):
        n = sum(
            1 for r in range(row0, min(row1, grid.nrows))
            if isinstance(grid.cell(r, c), str) and grid.cell(r, c).strip()
        )
        if n > best_count:
            best_col, best_count = c, n
    return best_col


def _subperiod_row(grid: Grid, period_row: int, data_row0: int, c0: int, c1: int) -> Optional[int]:
    """A row between the year header and the data whose cells parse as quarters/months."""
    for r in range(period_row + 1, max(period_row + 1, data_row0)):
        hits = sum(
            1 for c in range(c0, c1)
            if parse_quarter(grid.cell(r, c)) is not None or parse_month(grid.cell(r, c)) is not None
        )
        if hits >= 3:
            return r
    return None


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
                        if _axis_year(grid.cell(year_row, c)) is not None]
        c1 = (max(years_on_row) + 3) if years_on_row else grid.ncols
        # Fila de métricas = la última de encabezado justo encima de los datos… SI EXISTE.
        # Cuando el encabezado de años está pegado a los datos (año en la fila 7, Enero en
        # la 8) NO hay fila de métricas: el archivo publica una sola magnitud. La fórmula
        # anterior —max(year_row+1, first_month_row-1)— devolvía igual una fila, y caía
        # sobre la PRIMERA DE DATOS: cada columna quedaba bautizada con el valor de esa
        # celda (`remesas_6.280155040_6400002`). No es que no supiéramos nombrar la serie;
        # estábamos leyendo un dato como si fuera un rótulo.
        # ``year_row`` es Optional en la firma pero acá ya está resuelto (la rama exige
    # year_row_count >= 4); se ancla en un int para que el checker lo siga.
        year_row_i = int(year_row or 0)
        metric_row = first_month_row - 1 if first_month_row - 1 > year_row_i else None
        # Cinturón y tirantes: si la fila candidata trae mayoría de números, no es un
        # encabezado por más que la geometría lo permita. Vale para cualquier planilla
        # futura con un layout que no anticipamos.
        if metric_row is not None and _row_is_mostly_numeric(grid, metric_row, c0, c1):
            metric_row = None
        # A super-header sits between the years and the metrics when that gap has
        # sparse text labels (e.g. ACTIVOS / RESERVAS over BRUTOS / BRUTAS / NETAS).
        # Sin fila de métricas tampoco hay hueco donde pueda vivir un super-encabezado.
        super_row = None
        for r in range(year_row_i + 1,
                       metric_row if metric_row is not None else year_row_i + 1):
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
        # Distinct value columns must map to distinct series codes — never merge two
        # columns into one (e.g. "Acumulada" under both "Serie Original" and "Serie
        # Desestacionalizada"). Disambiguate slug collisions by column so the data
        # of two real series is never silently mixed.
        series: List[SeriesSpec] = []
        seen_codes: dict[str, int] = {}
        for c in value_cols:
            name = _header_name(grid, c, first_month_row)
            code = _slug(name)
            if code in seen_codes:
                code = f"{code}_c{c}"
            seen_codes[code] = c
            series.append(SeriesSpec(code=code, name=name, unit=None, value_col=c))
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

    # Matrix: many periods across a header row (years), series down the rows. Covers
    # national accounts, balance of payments, etc. — and the quarterly variants when
    # a sub-row carries E-M/A-J/J-S/O-D.
    if year_row_count >= 4:
        years_on_row = [c for c in range(grid.ncols)
                        if _axis_year(grid.cell(year_row, c)) is not None]
        c0, c1 = min(years_on_row), max(years_on_row) + 1
        label_col = _label_column(grid, c0, year_row + 1, grid.nrows)
        if label_col is not None:
            sub_row = _subperiod_row(grid, year_row, year_row + 4, c0, c1)
            freq = "quarterly" if sub_row is not None else "annual"
            data_start = (sub_row if sub_row is not None else year_row) + 1
            conf = min(0.85, 0.5 + 0.03 * min(year_row_count, 12))
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="matrix",
                data_row_start=data_start, period_header_row=year_row,
                subperiod_header_row=sub_row, label_col=label_col,
                value_col_start=c0, value_col_end=c1, frequency=freq,
                structure_hash=sh, confidence=round(conf, 2), method="heuristic",
                notes=f"matrix {freq}: {year_row_count} períodos en fila {year_row}",
            )

    # Quarterly period_rows: quarters (I-IV / E-M) down a column, year revealed by
    # a "Promedio YYYY" or bare-year marker row (e.g. PIB / deflactor trimestral).
    qcol, first_q_row, q_count = _quarter_column(grid)
    if qcol is not None and q_count >= 4 and _has_year_markers(grid, qcol):
        value_cols = _value_columns(grid, qcol, first_q_row)
        series = []
        seen_q: dict[str, int] = {}
        for c in value_cols:
            name = _header_name(grid, c, first_q_row)
            code = _slug(name)
            if code in seen_q:
                code = f"{code}_c{c}"
            seen_q[code] = c
            series.append(SeriesSpec(code=code, name=name, unit=None, value_col=c))
        if series:
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="period_rows",
                data_row_start=first_q_row, month_col=qcol,
                subtotal_year_regex=_SUBTOTAL_RE, series=series, frequency="trimestral",
                structure_hash=sh, confidence=round(min(0.82, 0.5 + 0.04 * q_count), 2),
                method="heuristic", notes="period_rows trimestral (marcador de año)",
            )

    # Annual period_rows: a column of years down the rows (no month axis).
    year_col, year_col_count, first_year_row = _year_column(grid)
    if year_col is not None and year_col_count >= 5 and year_col_count >= year_row_count:
        value_cols = _value_columns(grid, year_col, first_year_row)
        series = []
        seen: dict[str, int] = {}
        for c in value_cols:
            name = _header_name(grid, c, first_year_row)
            code = _slug(name)
            if code in seen:
                code = f"{code}_c{c}"
            seen[code] = c
            series.append(SeriesSpec(code=code, name=name, unit=None, value_col=c))
        if series:
            conf = min(0.8, 0.45 + 0.02 * year_col_count)
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="period_rows",
                data_row_start=first_year_row, month_col=None, year_col=year_col,
                series=series, frequency="annual", structure_hash=sh,
                confidence=round(conf, 2), method="heuristic",
                notes=f"period_rows annual: year_col={year_col}",
            )

    # Unresolved — let the interpreter take it.
    return ExtractionSpec(
        file=file, sheet=grid.name, orientation="period_rows",
        data_row_start=0, structure_hash=sh, confidence=0.0, method="heuristic",
        notes="sin eje de período detectado",
    )
