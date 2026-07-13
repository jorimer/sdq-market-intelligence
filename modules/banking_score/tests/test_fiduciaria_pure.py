"""Tests for the pure helpers of the fiduciary sync (no DB, no network).

``_income_hhi(comisiones, ingresos)`` — HHI of the two-way income split (comisiones
fiduciarias vs otros ingresos): 1.0 when a single source concentrates everything,
0.5 (= 1/n, n=2) on an even split, ``None`` when the inputs can't support it.
``_parse_period_end`` — tolerant ISO date parsing of the AI-extracted period_end.
"""
from datetime import date

import pytest

from modules.banking_score.fiduciaria_sync import _income_hhi, _parse_period_end


# ── _income_hhi ───────────────────────────────────────────────────
def test_hhi_single_income_source_is_one():
    # All income is comisiones → full concentration.
    assert _income_hhi(1000.0, 1000.0) == 1.0
    # All income is "otros" (zero comisiones) → also full concentration.
    assert _income_hhi(0.0, 1000.0) == 1.0


def test_hhi_even_split_is_one_over_n():
    # Two equal components (n=2) → HHI = 1/n = 0.5.
    assert _income_hhi(500.0, 1000.0) == 0.5


def test_hhi_uneven_split():
    # 1/3 vs 2/3 → (1/3)² + (2/3)² = 5/9, rounded to 4 decimals.
    assert _income_hhi(1000.0, 3000.0) == pytest.approx(round(5 / 9, 4))


def test_hhi_none_inputs_return_none():
    assert _income_hhi(None, 1000.0) is None    # no comisiones figure
    assert _income_hhi(500.0, None) is None     # no income figure
    assert _income_hhi(500.0, 0.0) is None      # zero income
    assert _income_hhi(500.0, -100.0) is None   # negative income


def test_hhi_clamps_out_of_range_share():
    # comisiones > ingresos (inconsistent extraction) → share clamped to 1 → HHI 1.0.
    assert _income_hhi(2000.0, 1000.0) == 1.0
    # negative comisiones → share clamped to 0 → HHI 1.0 (all "otros").
    assert _income_hhi(-50.0, 1000.0) == 1.0


def test_hhi_rounds_to_four_decimals():
    v = _income_hhi(1.0, 7.0)   # (1/7)² + (6/7)² = 37/49 = 0.75510204…
    assert v == round(37 / 49, 4) == 0.7551


# ── _parse_period_end ─────────────────────────────────────────────
def test_parse_period_end_iso_date():
    assert _parse_period_end("2024-12-31") == date(2024, 12, 31)


def test_parse_period_end_iso_datetime_truncates():
    # Only the first 10 chars are read → a timestamp still parses.
    assert _parse_period_end("2024-12-31T00:00:00") == date(2024, 12, 31)


def test_parse_period_end_invalid_inputs_return_none():
    assert _parse_period_end(None) is None
    assert _parse_period_end("") is None
    assert _parse_period_end("no-fecha") is None
    assert _parse_period_end("31/12/2024") is None   # non-ISO format
    assert _parse_period_end("2024-13-01") is None   # invalid month
