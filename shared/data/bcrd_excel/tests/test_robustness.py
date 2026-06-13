"""Regression tests for crashes the full-catalog run surfaced.

A corpus sweep is the real fuzzer: these two bugs killed files in production —
a chart-only sheet (Chartsheet has no ``iter_rows``) and a spec with a ``None``
row index (Claude may omit a field for its orientation), which hit
``0 <= None`` deep in ``Grid.cell``.
"""
from pathlib import Path

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, load_workbook

FIXTURES = Path(__file__).parent / "fixtures"


def test_chartsheet_workbook_loads():
    """Serie_TPM.xlsx has a 'Tasas' worksheet + a 'Gráfico' chartsheet; the loader
    must skip the chartsheet, not crash on it."""
    wb = load_workbook(FIXTURES / "Serie_TPM.xlsx")
    assert "Gráfico" not in wb.sheet_names  # chartsheet excluded
    spec = infer_spec(wb, "Serie_TPM.xlsx")
    recs = extract_records(wb, spec)
    assert len(recs) > 100  # the real data sheet is read fine


def test_grid_cell_none_index_safe():
    g = Grid(name="s", rows=[[1, 2], [3, 4]])
    assert g.cell(None, 0) is None
    assert g.cell(0, None) is None
    assert g.cell(0, 0) == 1


def test_extract_tolerates_none_indices():
    """A spec with a missing row index extracts nothing rather than crashing."""
    wb = load_workbook(FIXTURES / "ipc.xls")
    sheet = wb.grids[0].name
    # matrix without period_header_row
    s1 = ExtractionSpec(file="x", sheet=sheet, orientation="matrix",
                        data_row_start=5, period_header_row=None, label_col=0,
                        value_col_start=1)
    assert extract_records(wb, s1) == []
    # period_rows without data_row_start
    s2 = ExtractionSpec(file="x", sheet=sheet, orientation="period_rows",
                        data_row_start=None, month_col=0)
    assert extract_records(wb, s2) == []
