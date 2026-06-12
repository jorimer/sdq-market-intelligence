"""Tests for the BCRD historical parsers (IPC + exchange rates), real shapes."""
from datetime import date

from shared.data.bcrd_client import (
    FX_BUY_SERIES,
    FX_SELL_SERIES,
    INFLATION_YOY_SERIES,
    IPC_INDEX_SERIES,
    parse_fx_history,
    parse_ipc_history,
)
from shared.data.lineage import Lineage

LIN = Lineage(source="BCRD", license="x", fetched_at=date(2026, 6, 12))


def _by(records):
    out = {}
    for r in records:
        out.setdefault(r.series, {})[r.period] = r.value
    return out


def test_parse_ipc_history_index_and_derived_yoy():
    # 13 months so a YoY (Jan 1984 → Jan 1985) can be derived.
    payload = [{"month": m, "year": y, "indexValue": v} for (y, m, v) in [
        (1984, 1, 100.0), (1984, 6, 105.0), (1985, 1, 110.0),
    ]]
    recs = parse_ipc_history(payload, LIN)
    by = _by(recs)
    assert by[IPC_INDEX_SERIES]["1984-01"] == 100.0
    assert by[IPC_INDEX_SERIES]["1985-01"] == 110.0
    # derived YoY for 1985-01 = (110/100 - 1)*100 = 10.0
    assert by[INFLATION_YOY_SERIES]["1985-01"] == 10.0
    # no YoY for 1984-01 (no prior year)
    assert "1984-01" not in by.get(INFLATION_YOY_SERIES, {})


def test_parse_ipc_history_handles_wrapped_and_bad_rows():
    payload = {"items": [
        {"month": 1, "year": 2020, "indexValue": 120.0},
        {"month": "bad", "year": 2020, "indexValue": 1},  # skipped
    ]}
    by = _by(parse_ipc_history(payload, LIN))
    assert by[IPC_INDEX_SERIES] == {"2020-01": 120.0}


def test_parse_fx_history_month_end_usd_only():
    # FX wraps rows in a single {totalCount, items} object; keep month-end USD.
    payload = [{
        "totalCount": 3,
        "items": [
            {"currencyId": 1, "buyingValue": 58.0, "sellingValue": 58.5, "exchangeRateDate": "2026-06-01T00:00:00", "isDeleted": False},
            {"currencyId": 1, "buyingValue": 59.0, "sellingValue": 59.5, "exchangeRateDate": "2026-06-30T00:00:00", "isDeleted": False},
            {"currencyId": 2, "buyingValue": 70.0, "sellingValue": 71.0, "exchangeRateDate": "2026-06-30T00:00:00", "isDeleted": False},  # EUR → skipped
        ],
    }]
    by = _by(parse_fx_history(payload, LIN))
    # month-end (30th) USD values win
    assert by[FX_BUY_SERIES]["2026-06"] == 59.0
    assert by[FX_SELL_SERIES]["2026-06"] == 59.5


def test_parse_fx_history_skips_deleted():
    payload = [{"items": [
        {"currencyId": 1, "buyingValue": 1.0, "sellingValue": 1.0, "exchangeRateDate": "2025-01-15", "isDeleted": True},
    ]}]
    assert parse_fx_history(payload, LIN) == []


def test_parsers_empty():
    assert parse_ipc_history(None, LIN) == []
    assert parse_fx_history({}, LIN) == []
