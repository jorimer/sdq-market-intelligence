"""Tests for the ENCFT employment-by-activity connector."""
import io

import openpyxl
import pytest

from shared.data.encft_employment import (
    EmploymentClient,
    EmploymentError,
    build_employment_records,
    parse_ocupados_xlsx,
)
from shared.data.sector_crosswalk import ENCFT_BRANCHES

# (ONE label, value) for the 10 branches — toy 2-year panel whose Σ == Total.
_BRANCH_ROWS = [
    ("Agricultura y Ganadería", 400),
    ("Industrias Manufactureras1", 500),
    ("Electricidad, Gas y Agua", 30),
    ("Construcción ", 250),
    ("Comercio al por Mayor y Menor", 700),
    ("Hoteles, Bares y Restaurantes", 220),
    ("Transporte y Comunicaciones", 260),
    ("Intermediación Financiera y Seguros", 80),
    ("Administración Pública y Defensa", 160),
    ("Otros Servicios2", 800),
]
_YEARS = [2020, 2021]
_TOTAL = sum(v for _lbl, v in _BRANCH_ROWS)  # 3400


def _toy_workbook(branch_rows=_BRANCH_ROWS, total=_TOTAL) -> bytes:
    """Build an in-memory workbook mirroring the real ONE layout (Total/H/M per year)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["REPÚBLICA DOMINICANA: Población ocupada, 2020-2021"])  # title row
    header = ["Actividad económica"]
    for y in _YEARS:
        header += [y, None, None]                      # year at the Total column
    ws.append(header)
    sub = [None]
    for _ in _YEARS:
        sub += ["Total", "Hombres", "Mujeres"]
    ws.append(sub)
    # Total row, then the branches; each value repeated per year, with toy H/M splits.
    ws.append(["Total "] + [total, total - 1, 1] * len(_YEARS))
    for label, val in branch_rows:
        ws.append([label] + [val, val, 0] * len(_YEARS))
    ws.append(["Nota: Población de 15 años y más."])
    ws.append(["1 Incluye minas y canteras."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_returns_ten_branches_and_national_total():
    branches, national = parse_ocupados_xlsx(_toy_workbook())
    assert set(branches) == {b.key for b in ENCFT_BRANCHES}
    assert len(branches) == 10
    assert national == {2020: 3400.0, 2021: 3400.0}
    assert branches["industrias"] == {2020: 500.0, 2021: 500.0}
    # the national 'Total' row is NOT one of the branches
    assert "total" not in branches


def test_build_emits_one_record_per_branch_year():
    branches, national = parse_ocupados_xlsx(_toy_workbook())
    records = build_employment_records(branches, national)
    assert len(records) == 10 * len(_YEARS)
    assert all(r.series == "employment" for r in records)
    assert {r.dimension for r in records} == {b.key for b in ENCFT_BRANCHES}
    r = next(r for r in records if r.dimension == "agricultura" and r.period == "2020")
    assert r.value == 400.0 and r.lineage.source == "ONE"


def test_sum_deviation_fails_closed():
    """Σ branches must equal the workbook's Total row (anti-stacked-blocks guard)."""
    tampered = list(_BRANCH_ROWS)
    tampered[0] = (tampered[0][0], tampered[0][1] + 50)   # inflate one branch
    branches, national = parse_ocupados_xlsx(_toy_workbook(branch_rows=tampered))
    with pytest.raises(EmploymentError, match="Σ ramas"):
        build_employment_records(branches, national)


def test_unmapped_activity_row_fails_closed():
    """A branch the ONE renamed (with employment numbers) must raise, not be dropped."""
    renamed = list(_BRANCH_ROWS)
    renamed[1] = ("Pesca y Acuicultura", 500)            # not one of the 10 branches
    with pytest.raises(EmploymentError, match="sin mapear"):
        parse_ocupados_xlsx(_toy_workbook(branch_rows=renamed))


def test_missing_branch_fails_closed():
    branches, national = parse_ocupados_xlsx(_toy_workbook(branch_rows=_BRANCH_ROWS[:-1]))
    # the dropped 'Otros Servicios' row makes Σ≠Total, so the guard fires first
    with pytest.raises(EmploymentError):
        build_employment_records(branches, national)


def test_missing_branch_key_guard_in_isolation():
    """The 'ramas ausentes' guard fires even when the totals would otherwise match."""
    branches, national = parse_ocupados_xlsx(_toy_workbook())
    dropped = branches.pop("otros_servicios")
    # keep Σ==Total consistent so ONLY the missing-branch guard can fire
    national = {y: national[y] - dropped[y] for y in national}
    with pytest.raises(EmploymentError, match="ausentes"):
        build_employment_records(branches, national)


def test_branch_year_without_total_fails_closed():
    """A branch year with no matching 'Total' row can't be verified → raise."""
    branches, national = parse_ocupados_xlsx(_toy_workbook())
    national.pop(2021)  # drop one year's national control magnitude
    with pytest.raises(EmploymentError, match="sin fila 'Total'"):
        build_employment_records(branches, national)


def test_fixture_mode_reproducible_and_real():
    """The committed fixture loads to the 10 branches over the real 2008-2024 panel."""
    recs = EmploymentClient(mode="fixture").fetch()
    assert recs, "fixture vacío"
    assert {r.dimension for r in recs} == {b.key for b in ENCFT_BRANCHES}
    periods = {r.period for r in recs}
    assert "2008" in periods and "2024" in periods
    assert all(r.series == "employment" and r.unit for r in recs)
    # filtering by series/period works
    one = EmploymentClient(mode="fixture").fetch(series="employment", period="2024")
    assert len(one) == 10 and all(r.period == "2024" for r in one)
