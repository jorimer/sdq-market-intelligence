"""Tests for the pure period-selection of the audited-history ingest (offline)."""
from modules.pension_intel.financials_sync import select_history_periods


def _year(y, months):
    return {f"{y}-{m:02d}": f"https://sipen.gob.do/descarga/afp-x-{y}_{y}_{m:02d}_1.pdf"
            for m in months}


# Full months 2010-2011, plus a partial current year (2012) with no December.
_YEAR_FILES = {
    2010: _year(2010, range(1, 13)),
    2011: _year(2011, range(1, 13)),
    2012: _year(2012, [1, 3, 5, 6]),  # partial year, latest = 2012-06
}


def test_annual_picks_december_plus_latest_month():
    chosen = select_history_periods(_YEAR_FILES, since_year=2010, annual=True)
    # December of each complete year + the freshest month (2012-06, though not a December).
    assert set(chosen) == {"2010-12", "2011-12", "2012-06"}


def test_since_year_filters_older_years():
    chosen = select_history_periods(_YEAR_FILES, since_year=2011, annual=True)
    assert "2010-12" not in chosen
    assert set(chosen) == {"2011-12", "2012-06"}


def test_non_annual_takes_every_month():
    chosen = select_history_periods(_YEAR_FILES, since_year=2010, annual=False)
    assert len(chosen) == 12 + 12 + 4
    assert "2010-07" in chosen and "2012-06" in chosen


def test_latest_month_not_duplicated_when_it_is_december():
    yf = {2010: _year(2010, range(1, 13))}  # latest IS 2010-12
    chosen = select_history_periods(yf, since_year=2010, annual=True)
    assert chosen == {"2010-12": yf[2010]["2010-12"]}  # exactly one entry, no dup
