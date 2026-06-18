"""Tests for the OWID climate-disaster mortality connector. Offline (pure parse)."""
from shared.data.owid_disasters_client import parse_climate_mortality

_HEADER = ("entity,code,year,"
           "total_dead_per_100k_people_drought_yearly,"
           "total_dead_per_100k_people_earthquake_yearly,"
           "total_dead_per_100k_people_volcanic_activity_yearly,"
           "total_dead_per_100k_people_flood_yearly,"
           "total_dead_per_100k_people_landslide_yearly,"
           "total_dead_per_100k_people_extreme_weather_yearly,"
           "total_dead_per_100k_people_wildfire_yearly,"
           "total_dead_per_100k_people_extreme_temperature_yearly,"
           "total_dead_per_100k_people_all_disasters_yearly")


def _row(iso, year, flood="", quake="", extreme=""):
    # columns: drought, earthquake, volcanic, flood, landslide, extreme_weather,
    #          wildfire, extreme_temperature, all
    return f"X,{iso},{year},,{quake},,{flood},,{extreme},,,"


_SAMPLE = "\n".join([
    _HEADER,
    _row("DOM", 2001, flood="1.0", quake="50.0"),       # earthquake EXCLUDED
    _row("DOM", 2002, extreme="3.0"),                   # mean DOM = (1.0 + 3.0)/2 = 2.0
    _row("DOM", 1990, flood="99.0"),                    # before window → ignored
    _row("CHL", 2003, flood="0.2"),
])


def test_climate_only_excludes_seismic_and_means_window():
    out = parse_climate_mortality(_SAMPLE, ["DOM", "CHL"], year_from=2000)
    assert out["DOM"] == 2.0          # quake excluded; 1990 out of window; mean of 1.0 & 3.0
    assert out["CHL"] == 0.2


def test_restricts_to_panel():
    out = parse_climate_mortality(_SAMPLE, ["CHL"], year_from=2000)
    assert set(out) == {"CHL"}
