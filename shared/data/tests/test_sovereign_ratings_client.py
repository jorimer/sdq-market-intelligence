"""Tests del parser de ratings soberanos (Wikipedia) — puro, contra fixture real."""
import io
from pathlib import Path

from shared.data.sovereign_ratings_client import (
    _normalize_rating, _parse_date, parse_credit_rating_wikitext)

_FIXTURE = Path(__file__).parent / "fixtures" / "wikipedia_credit_ratings.wikitext"


def _wikitext() -> str:
    return io.open(_FIXTURE, encoding="utf-8").read()


def test_normalize_rating_dashes():
    assert _normalize_rating("BB−") == "BB-"      # Unicode minus U+2212
    assert _normalize_rating("BB–") == "BB-"      # en dash
    assert _normalize_rating(" BBB- ") == "BBB-"
    assert _normalize_rating("BB+") == "BB+"


def test_parse_date_iso():
    assert _parse_date("19 December 2022") == "2022-12-19"
    assert _parse_date("7 November 2025") == "2025-11-07"
    assert _parse_date("not a date") is None


def test_parse_covers_the_five_country_panel():
    panel = parse_credit_rating_wikitext(_wikitext())
    assert set(panel) == {"DO", "CR", "PA", "GT", "JM"}
    # every panel country carries the three agencies.
    for iso in panel:
        assert set(panel[iso]) == {"sp", "fitch", "moodys"}


def test_parse_normalizes_and_dates():
    panel = parse_credit_rating_wikitext(_wikitext())
    # S&P anchor: DR is BB with the LAST-ACTION date (2022), not an affirmation.
    assert panel["DO"]["sp"]["rating"] == "BB"
    assert panel["DO"]["sp"]["action_date"] == "2022-12-19"
    assert panel["DO"]["sp"]["outlook"] == "Stable"
    # Unicode minus normalized to ASCII in Fitch's BB-.
    assert panel["DO"]["fitch"]["rating"] == "BB-"
    assert panel["DO"]["fitch"]["action_date"] == "2025-11-07"
    # Panama S&P is investment grade BBB-.
    assert panel["PA"]["sp"]["rating"] == "BBB-"
    # Moody's grades kept in Moody's notation (mapped to the scale downstream).
    assert panel["DO"]["moodys"]["rating"] == "Ba3"


def test_parse_extracts_source_url_when_present():
    panel = parse_credit_rating_wikitext(_wikitext())
    assert panel["CR"]["sp"]["source_url"].startswith("https://")


def test_parse_ignores_non_panel_countries():
    # The fixture includes a Brazil row to prove filtering.
    panel = parse_credit_rating_wikitext(_wikitext())
    assert "BR" not in panel and "Brazil" not in panel


def test_parse_empty_wikitext_is_empty():
    assert parse_credit_rating_wikitext("") == {}
    assert parse_credit_rating_wikitext("no tables here") == {}
