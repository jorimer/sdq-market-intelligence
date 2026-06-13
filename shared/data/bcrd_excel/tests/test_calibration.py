"""Calibration — the heuristic engine must extract the *correct* values from the
three real BCRD files we already hold via the API (IMAE, IPC, reserves).

Ground-truth values are read straight from the published sheets; if extraction
drifts, these break. This is the proof that "the data comes out right" before the
engine is unleashed on the full catalog.
"""
from pathlib import Path

import pytest

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.validation import validate
from shared.data.bcrd_excel.workbook import Grid, Workbook, load_workbook

FIXTURES = Path(__file__).parent / "fixtures"


def _series(records, suffix):
    return {r.period: r.value for r in records if r.series.endswith(suffix)}


def _extract(filename):
    wb = load_workbook(FIXTURES / filename)
    spec = infer_spec(wb, filename)
    return spec, extract_records(wb, spec)


# ── IPC: year sparse in a column, months down a column ────────────
def test_ipc_year_in_column():
    spec, recs = _extract("ipc.xls")
    assert spec.orientation == "period_rows"
    assert spec.year_col is not None and spec.subtotal_year_regex is None
    idx = _series(recs, "indice_base_1999")
    assert idx["1982-01"] == pytest.approx(5.712, abs=1e-3)
    assert idx["1982-12"] == pytest.approx(6.118, abs=1e-3)
    assert "2010-01" in idx and len(idx) > 300  # deep monthly history


# ── IMAE: year only in trailing "Promedio YYYY" subtotal rows ─────
def test_imae_subtotal_year():
    spec, recs = _extract("imae.xlsx")
    assert spec.orientation == "period_rows"
    assert spec.subtotal_year_regex is not None  # block-delimited year
    idx = _series(recs, "serie_original_indice")
    assert idx["2007-01"] == pytest.approx(93.963, abs=1e-2)
    assert idx["2008-01"] == pytest.approx(103.097, abs=1e-2)
    # the "Promedio 2007" subtotal row must NOT leak in as a monthly obs
    assert all(len(p) == 7 for p in idx)  # every period is YYYY-MM


def test_imae_no_silent_series_merge():
    """Distinct value columns must map to distinct series — "Acumulada" appears
    under both "Serie Original" and "Serie Desestacionalizada"; merging them would
    mix two series into one. The engine must keep them apart (no duplicate periods).
    """
    _, recs = _extract("imae.xlsx")
    report = validate(recs, file="imae.xlsx")
    # every series has unique periods (no two columns collapsed into one code)
    assert all(s.duplicates == 0 for s in report.series), [
        (s.code, s.duplicates) for s in report.series if s.duplicates
    ]
    codes = [s.code for s in report.series]
    assert len(codes) == len(set(codes))  # codes themselves are unique


# ── Reserves: cross-tab with a 2-level header + a 2003 methodology break ──
def test_reservas_cross_tab():
    spec, recs = _extract("reservas_internacionales.xlsx")
    assert spec.orientation == "cross_tab"
    assert spec.super_header_row is not None  # ACTIVOS / RESERVAS super-header
    # old methodology (1985-2002): bare BRUTAS / NETAS
    brutas = _series(recs, ".brutas")
    netas = _series(recs, ".netas")
    assert brutas["1985-01"] == pytest.approx(255.0, abs=1e-6)
    assert netas["1985-01"] == pytest.approx(-381.1, abs=1e-6)
    assert brutas["1985-03"] == pytest.approx(312.7, abs=1e-6)
    # new methodology (2003+): the super-header disambiguates, footnotes stripped
    codes = {r.series.split(".")[-1] for r in recs}
    assert {"brutas", "netas", "activos_brutos", "reservas_brutas", "reservas_netas"} == codes
    assert "brutas_1" not in codes and "netas_2" not in codes  # no footnote artifacts
    assert _series(recs, "reservas_brutas")["2003-01"] == pytest.approx(583.3, abs=1e-6)
    assert _series(recs, "activos_brutos")["2003-01"] == pytest.approx(784.5, abs=1e-6)


# ── The validation gate trusts the clean output and dates it correctly ──
def test_validation_clean_reservas():
    _, recs = _extract("reservas_internacionales.xlsx")
    report = validate(recs, file="reservas_internacionales.xlsx", min_obs=6)
    assert len(report.series) == 5 and report.ok  # five real series, none flagged
    for s in report.series:
        assert s.n_obs > 100 and s.duplicates == 0
    # old and new blocks land on disjoint, correctly-dated period spans
    old = [s for s in report.series if s.code.endswith(".brutas")][0]
    new = [s for s in report.series if s.code.endswith(".reservas_brutas")][0]
    assert old.period_max < "2003" <= new.period_min


# ── Annual period_rows: a year column, no month axis ──────────────
def test_ipc_anual_period_rows():
    spec, recs = _extract("ipc_anual_base_2010.xls")
    assert spec.orientation == "period_rows"
    assert spec.month_col is None and spec.frequency == "annual"
    idx = _series(recs, "indice_base_enero_1999")
    assert idx["1984"] == pytest.approx(7.477, abs=1e-2)  # annual periods are "YYYY"
    assert all(len(p) == 4 for p in idx)  # every period is a bare year
    assert len(idx) >= 30 and "2019" in idx  # deep annual run, not a header artifact
    # the year buried in the "Bases 1999 y 2010" subtitle (row 2) must not start data
    assert spec.data_row_start > 4


# ── Matrix: periods across a header row, series down the rows ──────
def test_pib_gasto_matrix_annual():
    spec, recs = _extract("pib_gasto.xls")
    assert spec.orientation == "matrix" and spec.frequency == "annual"
    # exact code: the absolute-values block (a later "% structure" block reuses the
    # label and is kept distinct as consumo_final_rN — never merged with this one)
    cf = _series(recs, ".consumo_final")
    assert cf["1991"] == pytest.approx(106405.2, abs=1e-1)
    assert all(len(p) == 4 for p in cf)  # annual columns → "YYYY"
    # distinct concept rows are distinct series (codes unique, never merged)
    codes = [s.code for s in validate(recs).series]
    assert len(codes) == len(set(codes))


def test_matrix_quarterly_synthetic():
    """A quarterly matrix (years over a header row, E-M/A-J/J-S/O-D below) — built
    in code to exercise the quarter path without a heavy .xls fixture."""
    rows = [
        ["Conceptos", 2010, 2010, 2010, 2010, 2011, 2011, 2011, 2011],
        ["", "E-M", "A-J", "J-S", "O-D", "E-M", "A-J", "J-S", "O-D"],
        ["Cuenta Corriente", -250.8, -1238.1, -1222.6, -1312.0, -488.8, -1202.9, -1299.7, -1343.2],
        ["Balanza Comercial", -1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -7.0, -8.0],
    ]
    wb = Workbook(path="bop.xls", grids=[Grid(name="BOP", rows=rows)])
    spec = ExtractionSpec(
        file="bop.xls", sheet="BOP", orientation="matrix", data_row_start=2,
        period_header_row=0, subperiod_header_row=1, label_col=0,
        value_col_start=1, value_col_end=9, frequency="quarterly", unit="US$ MM",
    )
    recs = extract_records(wb, spec)
    cc = {r.period: r.value for r in recs if r.series.endswith(".cuenta_corriente")}
    assert cc["2010-Q1"] == pytest.approx(-250.8)
    assert cc["2010-Q4"] == pytest.approx(-1312.0)
    assert cc["2011-Q2"] == pytest.approx(-1202.9)
    assert sorted(cc) == ["2010-Q1", "2010-Q2", "2010-Q3", "2010-Q4",
                          "2011-Q1", "2011-Q2", "2011-Q3", "2011-Q4"]


# ── Cross-check against API-held values is the strongest signal ───
def test_crosscheck_matches_reference():
    _, recs = _extract("reservas_internacionales.xlsx")
    # reference = a few reserves levels as the API would report them (US$ MM)
    refs = {
        next(r.series for r in recs if r.series.endswith(".brutas")): {
            "1985-01": 255.0, "1985-03": 312.7,
        }
    }
    report = validate(recs, references=refs)
    cc = [s.crosscheck for s in report.series if s.crosscheck][0]
    assert cc.n_compared == 2 and cc.n_mismatch == 0 and cc.ok
