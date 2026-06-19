"""Tests for the TSS salary connector (Power BI querydata + DSR decode)."""
import pytest

from shared.data.tss_salary import (
    DROP_ACTIVITY,
    MIN_ACTIVITIES,
    TSSSalaryClient,
    TSSSalaryError,
    activity_key,
    build_salary_records,
    decode_dsr,
)

# Minimal DSR mirroring Power BI's shape: 2 dims (activity, year) + 1 measure,
# exercising the R-bitmask (column carried forward from the previous row).
_DSR = {"results": [{"result": {"data": {"dsr": {"DS": [{
    "ValueDicts": {"D0": ["Comercio", "Manufactura"], "D1": ["2024", "2025"]},
    "PH": [{"DM0": [
        {"S": [{"N": "G0", "DN": "D0"}, {"N": "G1", "DN": "D1"}, {"N": "M0"}],
         "C": [0, 0, 100.0]},                     # Comercio, 2024, 100
        {"C": [1, 200.0], "R": 1},                # reuse Comercio, 2025, 200
        {"C": [1, 0, 300.0]},                     # Manufactura, 2024, 300
        {"C": [1, 400.0], "R": 1},                # reuse Manufactura, 2025, 400
    ]}],
}]}}}}]}


def test_decode_dsr_reconstructs_matrix_with_reuse_bitmask():
    out = decode_dsr(_DSR)
    assert out == [
        ("Comercio", "2024", 100.0),
        ("Comercio", "2025", 200.0),
        ("Manufactura", "2024", 300.0),
        ("Manufactura", "2025", 400.0),
    ]


def test_decode_dsr_raises_on_odata_error():
    bad = {"results": [{"result": {"data": {"dsr": {"DataShapes": [{"odata.error": {
        "message": {"value": "invalid Measure reference"}}}]}}}}]}
    with pytest.raises(TSSSalaryError, match="rechazó"):
        decode_dsr(bad)


def test_decode_dsr_fails_closed_without_column_descriptor():
    # a DM0 row with no select descriptor S → structure changed → fail closed
    nodesc = {"results": [{"result": {"data": {"dsr": {"DS": [{
        "ValueDicts": {}, "PH": [{"DM0": [{"C": [0, 0, 1.0]}]}],
    }]}}}}]}
    with pytest.raises(TSSSalaryError, match="descriptor"):
        decode_dsr(nodesc)


def test_activity_key_normalizes():
    assert activity_key("Explotación de Minas y Canteras") == "explotacion_de_minas_y_canteras"
    assert activity_key("Electricidad, Gas y Agua") == "electricidad_gas_y_agua"
    assert activity_key("No identificado") == DROP_ACTIVITY


def test_build_records_drops_residual_and_stamps_provenance():
    # 15 real activities + the residual; the residual must be dropped.
    decoded = [(f"Actividad {i}", "2025", 1000.0 + i) for i in range(MIN_ACTIVITIES)]
    decoded.append(("No identificado", "2025", 17000.0))
    recs = build_salary_records(decoded)
    dims = {r.dimension for r in recs}
    assert DROP_ACTIVITY not in dims
    assert len(dims) == MIN_ACTIVITIES
    assert all(r.lineage.source == "TSS" and r.series == "avg_salary" for r in recs)


def test_build_records_fails_closed_when_too_few_activities():
    decoded = [(f"Actividad {i}", "2025", 1000.0) for i in range(MIN_ACTIVITIES - 1)]
    with pytest.raises(TSSSalaryError, match="actividades"):
        build_salary_records(decoded)


def test_fixture_mode_real_snapshot():
    recs = TSSSalaryClient(mode="fixture").fetch()
    assert recs, "fixture vacío"
    dims = {r.dimension for r in recs}
    assert len(dims) >= MIN_ACTIVITIES
    assert DROP_ACTIVITY not in dims
    # the verified mining figure (highest salary) is present and large
    mineria = [r.value for r in recs
               if r.dimension == "explotacion_de_minas_y_canteras" and r.period == "2025"]
    assert mineria and mineria[0] > 70000
    # series/period filtering works
    one = TSSSalaryClient(mode="fixture").fetch(series="avg_salary", period="2025")
    assert one and all(r.period == "2025" for r in one)
