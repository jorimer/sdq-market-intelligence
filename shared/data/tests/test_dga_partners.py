"""Tests for the DGA trade-by-partner connector (Power BI querydata + DSR decode).

The DSR decode is exercised against the real Power BI shape (5 columns: partner,
year, quarter, exp measure, imp measure), including the ``R`` reuse bitmask and the
string-encoded numerics the report emits. Fixture mode reads the committed real
snapshot. All offline.
"""
import pytest

from shared.data.dga_partners_client import (
    DGAPartnersClient,
    DGAPartnersError,
    MIN_PARTNERS,
    SERIES,
    build_query,
    parse_dimension,
    rows_to_records,
)
from shared.data.powerbi import PowerBIError, decode_dsr_rows

# DSR mirroring the DGA report: 3 dims (partner, year, quarter) + 2 measures,
# exercising the R-bitmask (columns carried forward) and a string-encoded measure.
_DSR = {"results": [{"result": {"data": {"dsr": {"DS": [{
    "ValueDicts": {"D0": ["Estados Unidos", "China"]},
    "PH": [{"DM0": [
        {"S": [{"N": "G0", "DN": "D0"}, {"N": "G1"}, {"N": "G2"}, {"N": "M0"}, {"N": "M1"}],
         "C": [0, 2025, 1, 1000.0, 2000.0]},              # US, 2025-Q1
        {"C": [2, "1500.5", 2500.0], "R": 3},             # reuse US+year, 2025-Q2, string exp
        {"C": [1, 2025, 1, 300.0, 900.0]},                # China, 2025-Q1
    ]}],
}]}}}}]}


def test_decode_dsr_rows_reconstructs_partner_matrix():
    out = decode_dsr_rows(_DSR, min_cols=5)
    assert out == [
        ["Estados Unidos", 2025, 1, 1000.0, 2000.0],
        ["Estados Unidos", 2025, 2, "1500.5", 2500.0],   # reused partner+year, string exp kept raw
        ["China", 2025, 1, 300.0, 900.0],
    ]


def test_decode_dsr_rows_fails_closed_on_odata_error():
    bad = {"results": [{"result": {"data": {"dsr": {"DataShapes": [{"odata.error": {
        "message": {"value": "invalid Measure reference 'FOB'"}}}]}}}}]}
    with pytest.raises(PowerBIError, match="rechazó"):
        decode_dsr_rows(bad, min_cols=5)


def test_rows_to_records_coerces_strings_and_stamps_provenance():
    decoded = decode_dsr_rows(_DSR, min_cols=5)
    recs = rows_to_records(decoded, keep_quarters=8, top_partners=30, min_partners=2)
    # 2025-Q1: US exp+imp + China exp+imp = 4; 2025-Q2: US exp+imp = 2 → 6 records
    assert len(recs) == 6
    assert all(r.series == SERIES and r.unit == "USD" for r in recs)
    assert all(r.lineage.source == "DGA (Power BI)" for r in recs)
    # the string-encoded export (1500.5) is coerced to float
    q2_us_exp = [r.value for r in recs
                 if r.period == "2025-Q2" and r.dimension == "export:Estados Unidos"]
    assert q2_us_exp == [1500.5]


def test_rows_to_records_keeps_only_recent_quarters():
    decoded = [
        ["US", y, q, 100.0, 50.0]
        for y in (2024, 2025) for q in (1, 2, 3, 4)
    ]  # 8 quarters, 1 partner
    # pad partners so MIN_PARTNERS is satisfied
    decoded += [["P%d" % i, 2025, 4, 10.0, 5.0] for i in range(MIN_PARTNERS)]
    recs = rows_to_records(decoded, keep_quarters=2, top_partners=30)
    periods = {r.period for r in recs}
    assert periods == {"2025-Q3", "2025-Q4"}   # only the last 2 quarters survive


def test_rows_to_records_fails_closed_on_too_few_partners():
    decoded = [["US", 2025, 1, 100.0, 50.0], ["China", 2025, 1, 20.0, 10.0]]
    with pytest.raises(DGAPartnersError, match="países socios"):
        rows_to_records(decoded)


def test_rows_to_records_fails_closed_on_empty():
    with pytest.raises(DGAPartnersError, match="no devolvió"):
        rows_to_records([])


def test_build_query_shape_uses_the_fob_measures():
    q = build_query(317763)
    cmd = q["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    assert q["modelId"] == 317763
    assert cmd["Query"]["Version"] == 2
    measures = [s["Measure"]["Property"] for s in cmd["Query"]["Select"] if "Measure" in s]
    assert measures == ["Total Fob Exp", "Total Fob Imp"]
    # partner + year + quarter + 2 measures = 5 projections
    assert cmd["Binding"]["Primary"]["Groupings"][0]["Projections"] == [0, 1, 2, 3, 4]


def test_parse_dimension_splits_direction_and_partner():
    assert parse_dimension("export:Estados Unidos") == ("export", "Estados Unidos")
    assert parse_dimension("import:China") == ("import", "China")


def test_fixture_mode_real_snapshot():
    recs = DGAPartnersClient(mode="fixture").fetch()
    assert recs, "fixture vacío"
    periods = {r.period for r in recs}
    assert len(periods) >= 4 and all("-Q" in p for p in periods)   # quarterly
    partners = {parse_dimension(r.dimension)[1] for r in recs}
    assert len(partners) >= MIN_PARTNERS
    # US is RD's #1 export partner — present with a large value in the latest quarter
    latest = max(periods, key=lambda p: tuple(int(x) for x in p.split("-Q")))
    us_exp = [r.value for r in recs
              if r.period == latest and r.dimension == "export:Estados Unidos"]
    assert us_exp and us_exp[0] > 1e8   # > US$100M/quarter
    # period filtering works
    one = DGAPartnersClient(mode="fixture").fetch(period=latest)
    assert one and all(r.period == latest for r in one)
