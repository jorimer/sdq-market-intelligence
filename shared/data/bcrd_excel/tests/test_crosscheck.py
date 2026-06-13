"""Cross-check primitives: YoY transform + period-by-period comparison."""
from shared.data.bcrd_excel.crosscheck import compare, yoy


def test_yoy_is_base_invariant():
    # two index series of different bases but identical growth → identical YoY
    base_a = {f"2020-{m:02d}": 100 + m for m in range(1, 13)}
    base_a.update({f"2021-{m:02d}": (100 + m) * 1.05 for m in range(1, 13)})  # +5% YoY
    base_b = {p: v * 7.3 for p, v in base_a.items()}  # rebased by a constant factor
    ya, yb = yoy(base_a), yoy(base_b)
    assert ya["2021-06"] == 5.0
    assert ya == yb  # YoY does not depend on the base


def test_yoy_skips_missing_and_gaps():
    s = {"2020-01": 100.0, "2021-01": 110.0, "2021-02": None}
    out = yoy(s)
    assert out == {"2021-01": 10.0}  # only the period with a year-ago base, value present


def test_compare_matches_within_tolerance():
    excel = {"2010-01": 5.7, "2010-02": 6.18, "2010-03": 4.0}
    api = {"2010-01": 5.7, "2010-02": 6.17, "2010-03": 9.9}  # last one is way off
    res = compare(excel, api, rel_tol=0.0, abs_tol=0.15)
    assert res.n_compared == 3
    assert res.n_match == 2 and res.n_mismatch == 1
    assert not res.ok  # any mismatch → not ok
    assert res.examples[0]["period"] == "2010-03"


def test_compare_levels_relative_tolerance():
    excel = {"2026-05": 15771.1}
    api = {"2026-05": 15770.0}  # 0.007% off → within 2% rel tol
    res = compare(excel, api, rel_tol=0.02, abs_tol=0.0)
    assert res.n_compared == 1 and res.ok


def test_compare_no_overlap():
    res = compare({"2010-01": 1.0}, {"2011-01": 1.0}, rel_tol=0.02, abs_tol=0.0)
    assert res.n_compared == 0 and not res.ok  # nothing overlapping → not ok
