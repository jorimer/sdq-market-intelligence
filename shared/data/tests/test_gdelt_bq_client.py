"""Tests for the GDELT-BigQuery connector's pure logic (no BigQuery needed)."""
from shared.data.gdelt_bq_client import (
    FIPS_TO_ISO2,
    GKG_TABLE,
    build_query,
    rows_to_records,
)


def test_build_query_is_partition_pruned_and_parameterized():
    q = build_query()
    assert GKG_TABLE in q
    assert "_PARTITIONTIME" in q            # partition pruning → free-tier safe
    assert "@days" in q and "@fips" in q     # parameterized
    assert "PROTEST" in q and "ECON_SANCTIONS" in q  # unrest + sanctions themes


def test_fips_map_covers_peer_set():
    # FIPS 10-4 ≠ ISO2 para varios (DR→DO, CS→CR, PM→PA…); panel completo de 24.
    assert FIPS_TO_ISO2["DR"] == "DO" and FIPS_TO_ISO2["CS"] == "CR"
    assert FIPS_TO_ISO2["VE"] == "VE" and FIPS_TO_ISO2["BR"] == "BR"
    assert len(FIPS_TO_ISO2) == 24 and len(set(FIPS_TO_ISO2.values())) == 24


def test_rows_to_records_maps_fips_and_three_vars():
    rows = [
        {"fips": "DR", "news_sentiment": -2.5, "unrest_shocks": 3.1, "sanctions_signal": 0.4},
        {"fips": "CS", "news_sentiment": 1.0, "unrest_shocks": None, "sanctions_signal": 0.0},
        {"fips": "ZZ", "news_sentiment": 9.9, "unrest_shocks": 1.0, "sanctions_signal": 1.0},  # unknown → skip
    ]
    recs = rows_to_records(rows)
    by = {(r.dimension, r.series): r.value for r in recs}
    assert "ZZ" not in {r.dimension for r in recs}        # unknown FIPS dropped
    assert by[("DO", "news_sentiment")] == -2.5            # FIPS DR → ISO2 DO
    assert by[("DO", "sanctions_signal")] == 0.4
    assert by[("CR", "unrest_shocks")] is None            # None preserved (rubric fallback)
    assert {r.series for r in recs} == {"news_sentiment", "unrest_shocks", "sanctions_signal"}
    assert recs[0].lineage.source == "GDELT_BQ"


def test_rows_to_records_empty():
    assert rows_to_records([]) == []
