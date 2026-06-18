"""Tests for the HURDAT2 hurricane-exposure connector. Offline (pure functions)."""
from shared.data.hurdat2_client import (
    hurdat2_client,
    hurricane_exposure,
    parse_hurdat2,
)

# Two storms: one tracking over Hispaniola (near DOM), one a depression far south.
_SAMPLE = """\
AL012023,            NEARDR,      3,
20230901, 0000,  , TS, 18.5N,  70.0W,  60, 1000,
20230901, 0600,  , HU, 19.0N,  71.0W,  95, 980,
20230901, 1200,  , HU, 20.0N,  72.0W,  90, 985,
AL022023,           FARAWAY,      2,
20230810, 0000,  , TD, 12.0N,  30.0W,  25, 1008,
20230810, 0600,  , TD, 12.5N,  31.0W,  30, 1008,
AL032023,          WEAKNEAR,      1,
20230705, 0000,  , TD, 18.6N,  70.1W,  30, 1009,
"""


def test_parse_keeps_only_ts_plus():
    storms = parse_hurdat2(_SAMPLE)
    # NEARDR (peak 95kt) qualifies; FARAWAY (30kt) and WEAKNEAR (30kt) are below TS.
    assert len(storms) == 1
    s = storms[0]
    assert s["year"] == 2023 and s["max_wind"] == 95 and len(s["track"]) == 3


def test_exposure_high_near_track_zero_far():
    storms = parse_hurdat2(_SAMPLE)
    exp = hurricane_exposure(["DOM", "CHL"], storms, latest_year=2023, window_years=30)
    assert exp["DOM"] > 0          # the storm tracked over Hispaniola
    assert exp["CHL"] == 0.0       # no Atlantic storm near Chile → real zero, not missing


def test_unknown_country_omitted():
    exp = hurricane_exposure(["DOM", "ZZZ"], parse_hurdat2(_SAMPLE), latest_year=2023)
    assert "ZZZ" not in exp        # not in COUNTRY_REFS → omitted (never fabricated)


def test_latest_file_url_picks_newest():
    html = (
        'hurdat2-1851-2021-041922.txt hurdat2-1851-2023-051124.txt '
        'hurdat2-1851-2022-050423.txt'
    )
    url = hurdat2_client.latest_file_url(html)
    assert url.endswith("hurdat2-1851-2023-051124.txt")
