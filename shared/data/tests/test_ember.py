"""Tests for the Ember transition connector (fossil share + carbon intensity)."""
from shared.data.ember_client import parse_transition

_HEADER = ("Area,ISO 3 code,Year,Area type,Continent,Ember region,EU,OECD,G20,G7,"
           "ASEAN,Category,Subcategory,Variable,Unit,Value,YoY absolute change,YoY % change")


def _row(iso, year, cat, sub, var, unit, value):
    cells = ["X", iso, str(year), "Country", "", "", "", "", "", "", "",
             cat, sub, var, unit, str(value), "", ""]
    return ",".join(cells)


_SAMPLE = "\n".join([
    _HEADER,
    _row("DOM", 2024, "Electricity generation", "Aggregate fuel", "Fossil", "%", 74.0),
    _row("DOM", 2025, "Electricity generation", "Aggregate fuel", "Fossil", "%", 76.19),   # latest wins
    _row("DOM", 2025, "Power sector emissions", "CO2 intensity", "CO2 intensity", "gCO2/kWh", 537.48),
    _row("DOM", 2025, "Electricity generation", "Aggregate fuel", "Fossil", "TWh", 17.28),  # not %, ignored
    _row("CHL", 2025, "Electricity generation", "Aggregate fuel", "Fossil", "%", 33.62),
    _row("CHL", 2025, "Power sector emissions", "CO2 intensity", "CO2 intensity", "gCO2/kWh", 290.51),
    _row("USA", 2025, "Electricity generation", "Aggregate fuel", "Fossil", "%", 60.0),     # out of panel
])


def test_parse_picks_latest_and_right_variables():
    out = parse_transition(_SAMPLE, ["DOM", "CHL"])
    assert out["DOM"]["fossil_dependence"] == 76.19          # 2025 beats 2024, % not TWh
    assert out["DOM"]["carbon_intensity"] == 537.48
    assert out["CHL"]["fossil_dependence"] == 33.62


def test_parse_restricts_to_panel():
    out = parse_transition(_SAMPLE, ["DOM"])
    assert set(out) == {"DOM"}                                # USA/CHL excluded
