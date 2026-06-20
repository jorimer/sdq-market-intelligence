"""Tests for the DGII fiscal-pulse connector (recaudación por grupo de impuesto)."""
import io

import openpyxl
import pytest

from shared.data.dgii_client import (
    GROUPS,
    SHEET,
    DGIIClient,
    DGIIError,
    build_records,
    latest_zip_per_year,
    parse_recaudacion_xlsx,
)

# (UPPERCASE label as the DGII writes it, monthly value) for the 7 top-level groups.
_GROUP_ROWS = [
    ("IMPUESTOS SOBRE LOS INGRESOS", 1000.0),
    ("IMPUESTOS SOBRE LA PROPIEDAD", 200.0),
    ("IMPUESTOS INTERNOS SOBRE MERCANCÍAS Y SERVICIOS", 800.0),
    ("IMPUESTOS S/EL COMERCIO Y LAS TRANSACCIONES COMERCIO EXTERIOR", 50.0),
    ("IMPUESTOS ECOLÓGICOS", 10.0),
    ("INGRESOS POR CONTRAPRESTACIÓN", 20.0),
    ("OTROS  INGRESOS", 30.0),  # the real sheet has a double space
]
_MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
           "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _toy_workbook(year="2026", n_months=3, group_rows=None) -> bytes:
    """Build an in-memory Excel mirroring the DGII 'Recaudo Histórico Mensual' sheet."""
    rows = group_rows if group_rows is not None else _GROUP_ROWS
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(["RECAUDACION MENSUAL DGII"])
    ws.append([f"Año {year}"])
    ws.append(["(En millones de RD$)"])
    ws.append(["Conceptos"] + _MONTHS + ["Total"])
    ws.append([])
    for label, val in rows:
        # months 1..n_months have the value; the rest of the year is 0 (future)
        monthly = [val if i < n_months else 0 for i in range(12)]
        # a sub-item under each group (mixed-case, must be ignored)
        ws.append([label] + monthly + [val * n_months])
        ws.append([f"- Sub de {label.title()}"] + monthly + [val * n_months])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_returns_seven_groups_and_months():
    year, groups = parse_recaudacion_xlsx(_toy_workbook(n_months=3))
    assert year == "2026"
    assert set(groups) == {s for s, _f in GROUPS}          # all 7 top-level groups
    assert sorted(groups["ingresos"]) == [1, 2, 3]         # only the 3 real months
    assert groups["ingresos"][1] == 1000.0
    assert groups["otros"][2] == 30.0                       # double-space label matched


def test_parse_skips_future_zero_months():
    _year, groups = parse_recaudacion_xlsx(_toy_workbook(n_months=2))
    assert sorted(groups["propiedad"]) == [1, 2]            # months 3-12 (value 0) dropped


def test_parse_fails_closed_on_missing_group():
    rows = _GROUP_ROWS[:-1]  # drop "OTROS INGRESOS"
    with pytest.raises(DGIIError, match="ausentes"):
        parse_recaudacion_xlsx(_toy_workbook(group_rows=rows))


def test_parse_fails_closed_without_sheet():
    wb = openpyxl.Workbook()
    wb.active.title = "Otra Hoja"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(DGIIError, match="ausente"):
        parse_recaudacion_xlsx(buf.getvalue())


def test_build_records_emits_groups_plus_total():
    year, groups = parse_recaudacion_xlsx(_toy_workbook(n_months=2))
    recs = build_records(year, groups)
    dims = {r.dimension for r in recs}
    assert dims == {s for s, _f in GROUPS} | {"total"}
    # total month 1 = sum of the 7 groups
    tot1 = next(r.value for r in recs if r.dimension == "total" and r.period == "2026-01")
    assert tot1 == pytest.approx(1000 + 200 + 800 + 50 + 10 + 20 + 30)
    assert all(r.series == "recaudacion" and r.lineage.source == "DGII" for r in recs)


def test_latest_zip_per_year_picks_most_complete():
    html = """
      <a href="/estadisticas/x/Documents/2025/Recaudacion enero-marzo 2025.zip">a</a>
      <a href="/estadisticas/x/Documents/2025/Recaudacion enero-diciembre 2025.zip">b</a>
      <a href="/estadisticas/x/Documents/2026/Recaudacion enero-mayo 2026.zip">c</a>
    """
    by_year = latest_zip_per_year(html)
    assert set(by_year) == {"2025", "2026"}
    assert "enero-diciembre 2025" in by_year["2025"]        # most complete 2025 wins
    assert "enero-mayo 2026" in by_year["2026"]


def test_fixture_mode_real_snapshot():
    recs = DGIIClient(mode="fixture").fetch()
    assert recs, "fixture vacío"
    assert "total" in {r.dimension for r in recs}
    assert {s for s, _f in GROUPS}.issubset({r.dimension for r in recs})
    # periods are YYYY-MM
    assert all(len(r.period) == 7 and r.period[4] == "-" for r in recs)
    one = DGIIClient(mode="fixture").fetch(series="recaudacion", period="2026-01")
    assert one and all(r.period == "2026-01" for r in one)
