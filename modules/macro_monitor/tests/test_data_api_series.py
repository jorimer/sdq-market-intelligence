"""Tests de la superficie de Data API del monitor macro (series canónicas BCRD).

Este es el productor real de series de la Fase 1 — lo que consume el primer cliente
(SDQ-PMS). Lo que se protege: la licencia fail-closed (una serie con linaje incompleto
no se redistribuye) y el corte point-in-time REAL por fecha de publicación.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.models.models import MacroSeries
from modules.macro_monitor.service import (
    canonical_series_for_api,
    series_observations_for_api,
)
from shared.database.base import Base

LICENSE = "datos oficiales BCRD — uso público con cita"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MacroSeries.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _obs(db, code, period, value, *, license_=LICENSE, published=None, unit="%",
         source="BCRD", frequency="quarterly"):
    db.add(MacroSeries(series_code=code, period=period, value=value, unit=unit,
                       frequency=frequency, source=source, license=license_,
                       published_at=published))
    db.commit()


# ─── Descriptores ─────────────────────────────────────────────────────


def test_describes_every_series_it_has(db):
    _obs(db, "gdp_growth", "2024", 5.1)
    _obs(db, "gdp_growth", "2025", 4.8)
    _obs(db, "usd_dop", "2025", 60.5, unit="DOP")
    described = {d["code"]: d for d in canonical_series_for_api(db)}
    assert set(described) == {"gdp_growth", "usd_dop"}
    assert described["gdp_growth"]["n_obs"] == 2
    assert described["gdp_growth"]["period_first"] == "2024"
    assert described["gdp_growth"]["period_latest"] == "2025"
    assert described["gdp_growth"]["license"] == LICENSE
    assert described["gdp_growth"]["source"] == "BCRD"


def test_a_new_series_appears_without_registering_it_anywhere(db):
    """Auto-extensión en el productor: ingerir una serie nueva la describe sola."""
    _obs(db, "gdp_growth", "2025", 4.8)
    assert [d["code"] for d in canonical_series_for_api(db)] == ["gdp_growth"]
    _obs(db, "reserves", "2025", 15000.0, unit="MM US$")
    assert sorted(d["code"] for d in canonical_series_for_api(db)) == \
        ["gdp_growth", "reserves"]


def test_license_is_fail_closed_when_one_observation_lacks_it(db):
    """Una fila sin licencia deja la serie sin licencia → el manifiesto la retiene.
    Estricto a propósito: el linaje mezclado es justo donde el error saldría caro."""
    _obs(db, "gdp_growth", "2024", 5.1)
    _obs(db, "gdp_growth", "2025", 4.8, license_=None)
    assert canonical_series_for_api(db)[0]["license"] is None


def test_mixed_licenses_also_fail_closed(db):
    _obs(db, "gdp_growth", "2024", 5.1)
    _obs(db, "gdp_growth", "2025", 4.8, license_="otra licencia distinta")
    assert canonical_series_for_api(db)[0]["license"] is None


def test_frequency_is_unknown_when_the_series_mixes_cadences(db):
    _obs(db, "cpi", "2025-01", 1.0, frequency="monthly")
    _obs(db, "cpi", "2025-Q1", 3.0, frequency="quarterly")
    assert canonical_series_for_api(db)[0]["frequency"] == "unknown"


# ─── Observaciones ────────────────────────────────────────────────────


def test_observations_are_period_ordered_with_lineage(db):
    _obs(db, "gdp_growth", "2025", 4.8, published=date(2026, 2, 1))
    _obs(db, "gdp_growth", "2024", 5.1, published=date(2025, 2, 1))
    out = series_observations_for_api(db, "gdp_growth")
    assert [o["period"] for o in out] == ["2024", "2025"]
    assert out[0]["published_at"] == "2025-02-01" and out[0]["source"] == "BCRD"


def test_missing_value_is_null_with_a_reason_never_zero(db):
    _obs(db, "gdp_growth", "2025", None)
    out = series_observations_for_api(db, "gdp_growth")
    assert out[0]["value"] is None and out[0]["reason"]


def test_unknown_series_returns_empty(db):
    assert series_observations_for_api(db, "no_existe") == []


def test_start_and_end_filter_by_period(db):
    for year, val in (("2023", 1.0), ("2024", 2.0), ("2025", 3.0)):
        _obs(db, "gdp_growth", year, val)
    out = series_observations_for_api(db, "gdp_growth", start="2024", end="2024")
    assert [o["period"] for o in out] == ["2024"]


def test_limit_keeps_the_most_recent(db):
    for year, val in (("2023", 1.0), ("2024", 2.0), ("2025", 3.0)):
        _obs(db, "gdp_growth", year, val)
    out = series_observations_for_api(db, "gdp_growth", limit=2)
    assert [o["period"] for o in out] == ["2024", "2025"]


# ─── Point-in-time real ───────────────────────────────────────────────


def test_as_of_cuts_by_publication_date(db):
    _obs(db, "gdp_growth", "2024", 5.1, published=date(2025, 2, 1))
    _obs(db, "gdp_growth", "2025", 4.8, published=date(2026, 2, 1))
    out = series_observations_for_api(db, "gdp_growth", as_of="2025-06-01")
    assert [o["period"] for o in out] == ["2024"]


def test_as_of_raises_when_the_lineage_cannot_honor_it(db):
    """Sin fecha de publicación no hay point-in-time posible: se levanta en vez de
    devolver la serie de hoy con una etiqueta falsa."""
    _obs(db, "gdp_growth", "2024", 5.1, published=None)
    with pytest.raises(ValueError, match="point-in-time"):
        series_observations_for_api(db, "gdp_growth", as_of="2025-01-01")


def test_malformed_as_of_is_rejected(db):
    _obs(db, "gdp_growth", "2024", 5.1, published=date(2025, 2, 1))
    with pytest.raises(ValueError, match="as_of"):
        series_observations_for_api(db, "gdp_growth", as_of="ayer")


def test_frequency_is_derived_from_the_period_format_when_not_declared(db):
    """El ingestor no puebla ``frequency``; derivarla del período canónico evita que
    TODA serie se reporte como 'unknown' sin necesidad."""
    _obs(db, "cpi", "2025-01", 1.0, frequency=None)
    _obs(db, "cpi", "2025-02", 1.2, frequency=None)
    assert canonical_series_for_api(db)[0]["frequency"] == "monthly"


def test_derived_frequency_covers_annual_and_quarterly(db):
    _obs(db, "gdp_growth", "2024", 5.0, frequency=None)
    _obs(db, "gdp_growth", "2025", 4.8, frequency=None)
    _obs(db, "roa", "2025-Q1", 1.0, frequency=None)
    _obs(db, "roa", "2025-Q2", 1.1, frequency=None)
    by = {d["code"]: d["frequency"] for d in canonical_series_for_api(db)}
    assert by == {"gdp_growth": "annual", "roa": "quarterly"}


def test_declared_frequency_wins_over_the_derived_one(db):
    _obs(db, "cpi", "2025-01", 1.0, frequency="monthly")
    _obs(db, "cpi", "2025-02", 1.2, frequency="monthly")
    assert canonical_series_for_api(db)[0]["frequency"] == "monthly"


# ─── Balanza de pagos: dos manuales, dos series, jamás encadenadas ────


def test_balance_of_payments_series_declare_their_manual(db):
    """El BCRD publica la balanza bajo dos ediciones del manual del FMI. En 2010 —el
    único año que ambas publican— las remesas difieren 23%. Encadenarlas fabricaría un
    salto que no ocurrió, así que cada serie declara su manual y que no se empalma."""
    _obs(db, "bcrd.xls.bpagos_6.i_cuenta_corriente", "2024", -3500.0)
    _obs(db, "bcrd.xls.bpagos.i_cuenta_corriente", "2005", -473.0)
    by = {d["code"]: d for d in canonical_series_for_api(db)}

    vigente = by["bcrd.xls.bpagos_6.i_cuenta_corriente"]["note"]
    assert "MBP6" in vigente and "VIGENTE" in vigente
    assert "NO encadenar" in vigente

    historica = by["bcrd.xls.bpagos.i_cuenta_corriente"]["note"]
    assert "MBP5" in historica and "DESCONTINUADA" in historica
    assert "bpagos_6" in historica          # nombra a su contraparte, no la deja adivinar


def test_the_two_manuals_never_collapse_into_one_code(db):
    """Códigos distintos = series distintas en el catálogo. Si compartieran código, el
    consumidor recibiría un empalme silencioso de dos metodologías."""
    _obs(db, "bcrd.xls.bpagos_6.i_cuenta_corriente", "2010", -4024.0)
    _obs(db, "bcrd.xls.bpagos.i_cuenta_corriente", "2010", -4330.0)
    codes = [d["code"] for d in canonical_series_for_api(db)]
    assert len(codes) == 2 and len(set(codes)) == 2


def test_an_unrelated_series_carries_no_methodology_note(db):
    """La nota es excepcional: solo donde hay una trampa real que declarar."""
    _obs(db, "gdp_growth", "2025", 4.8)
    assert canonical_series_for_api(db)[0]["note"] == ""
