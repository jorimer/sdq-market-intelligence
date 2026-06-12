"""Tests for the BCRD live parser (real response shapes, captured 2026-06)."""
from datetime import date

from shared.data.bcrd_client import (
    _period_from_date,
    _period_from_label,
    _slug,
    parse_variable,
)
from shared.data.lineage import Lineage

LINEAGE = Lineage(source="BCRD", license="x", fetched_at=date(2026, 6, 12))


def _by_series(records):
    return {r.series: r for r in records}


# ── helpers ───────────────────────────────────────────────────────
def test_slug_is_accent_insensitive_and_stable():
    assert _slug("Inflación Subyacente") == "inflacion_subyacente"
    assert _slug("Tasas de interés") == "tasas_de_interes"
    assert _slug("  ") == "x"


def test_period_from_date():
    assert _period_from_date("13/05/2026") == "2026-05"
    assert _period_from_date("11/06/2026") == "2026-06"
    assert _period_from_date("basura") is None


def test_period_from_label_months_and_ranges():
    assert _period_from_label("Abril 2026") == "2026-04"
    assert _period_from_label("Diciembre 2025") == "2025-12"
    assert _period_from_label("Ene-Abr 2026") is None  # range → skip
    assert _period_from_label("") is None


# ── value-group (metrics are series, period from date) ────────────
def test_parse_inflacion_value_group():
    payload = {
        "name": "Inflación",
        "values": [
            {
                "name": "Inflación",
                "values": [
                    {"name": "Interanual", "value": 5.35},
                    {"name": "Acumulada", "value": 1.5},
                    {"name": "Mensual", "value": 0.31},
                ],
                "date": "13/05/2026",
            },
            {
                "name": "Inflación Subyacente",
                "values": [{"name": "Interanual", "value": 4.86}],
                "date": "13/05/2026",
            },
        ],
    }
    recs = parse_variable("inflacion", payload, LINEAGE, "2026-06")
    by = _by_series(recs)
    assert by["bcrd.inflacion.inflacion.interanual"].value == 5.35
    assert by["bcrd.inflacion.inflacion.interanual"].period == "2026-05"
    assert by["bcrd.inflacion.inflacion_subyacente.interanual"].value == 4.86
    assert len(recs) == 4


def test_parse_monetarias_interest_rates():
    payload = {
        "name": "Monetarias",
        "values": [{
            "name": "Tasas de interés",
            "values": [
                {"name": "Interbancaria", "value": 10.03},
                {"name": "Activa", "value": 13.8},
                {"name": "Pasiva", "value": 7.33},
            ],
            "date": "13/05/2026",
        }],
    }
    by = _by_series(parse_variable("monetarias", payload, LINEAGE, "2026-06"))
    assert by["bcrd.monetarias.tasas_de_interes.activa"].value == 13.8
    assert by["bcrd.monetarias.tasas_de_interes.activa"].period == "2026-05"


# ── period-group (metric name IS the period, e.g. IMAE) ───────────
def test_parse_sector_real_period_group_skips_ranges():
    payload = {
        "name": "Sector Real",
        "values": [{
            "name": "Imaes",
            "values": [
                {"name": "Abril 2026", "value": 3.8},
                {"name": "Ene-Abr 2026", "value": 4.0},  # range → skipped
            ],
        }],
    }
    recs = parse_variable("sector_real", payload, LINEAGE, "2026-06")
    # one series for the group; only the clean month survives
    assert len(recs) == 1
    r = recs[0]
    assert r.series == "bcrd.sector_real.imaes"
    assert r.period == "2026-04"
    assert r.value == 3.8


def test_parse_falls_back_to_default_period_without_date():
    payload = {"name": "X", "values": [{
        "name": "Grupo", "values": [{"name": "Compra", "value": 58.68}],
    }]}
    # metric "Compra" isn't a period and there's no date → value-group, default period
    recs = parse_variable("sector_externo", payload, LINEAGE, "2026-06")
    assert recs[0].period == "2026-06"
    assert recs[0].series == "bcrd.sector_externo.grupo.compra"


def test_parse_handles_missing_and_non_numeric_values():
    payload = {"name": "X", "values": [{
        "name": "G", "values": [{"name": "a", "value": None}, {"name": "b", "value": "n/d"}],
        "date": "13/05/2026",
    }]}
    recs = parse_variable("inflacion", payload, LINEAGE, "2026-06")
    assert all(r.value is None for r in recs)


def test_parse_empty_payload():
    assert parse_variable("inflacion", {}, LINEAGE, "2026-06") == []
    assert parse_variable("inflacion", None, LINEAGE, "2026-06") == []
