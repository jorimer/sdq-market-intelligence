"""Naturaleza estadística: se DECLARA desde lo que el emisor escribió, no se adivina."""
import pytest

from shared.data.series_nature import (
    FLOW, INDEX, RATE, STOCK, UNKNOWN, infer_nature, percent_change_is_valid,
)


@pytest.mark.parametrize("unit,label,esperado", [
    # La UNIDAD manda: es lo que el emisor declaró en su planilla.
    ("%", "Inflación interanual", RATE),
    ("% interanual", "PIB real", RATE),
    ("porcentaje del PIB", "Deuda pública", RATE),
    ("MM US$", "Exportaciones", FLOW),
    ("Millones de RD$", "Consumo final", FLOW),
    ("índice 2018=100", "IMAE", INDEX),
    # Moneda + etiqueta de saldo → stock, no flujo.
    ("MM US$", "Reservas internacionales netas", STOCK),
    ("Millones de dólares", "Posición de inversión internacional", STOCK),
    # Sin unidad, decide la etiqueta.
    (None, "Tasa de desocupación", RATE),
    (None, "Ponderación de la actividad", RATE),
    (None, "Saldo de la deuda externa", STOCK),
    (None, "Índice de precios al consumidor", INDEX),
    # Sin evidencia NO se inventa.
    (None, None, UNKNOWN),
    ("", "", UNKNOWN),
])
def test_infer_nature(unit, label, esperado):
    assert infer_nature(unit, label) == esperado


def test_the_unit_beats_the_label():
    """Si el emisor dice '%', es una tasa aunque la etiqueta suene a saldo."""
    assert infer_nature("%", "Reservas internacionales") == RATE


def test_percent_change_validity_by_nature():
    assert percent_change_is_valid(FLOW) and percent_change_is_valid(INDEX)
    # Una tasa NO: su variación va en puntos. Un stock se decide observación a
    # observación (puede cruzar el cero). Lo desconocido, nunca.
    assert not percent_change_is_valid(RATE)
    assert not percent_change_is_valid(STOCK)
    assert not percent_change_is_valid(UNKNOWN)


def test_the_code_helps_when_there_is_no_label():
    assert infer_nature(None, None, "bcrd.xls.tasa_desocupacion.anual") == RATE
    assert infer_nature(None, None, "bcrd.xls.piianual.activos") == STOCK


# ─── Códigos propios: se DECLARAN, no se adivinan ─────────────────────


@pytest.mark.parametrize("code,esperado", [
    ("public_debt_gdp", RATE),     # es % del PIB: su variación va en puntos
    ("gdp_growth", RATE),
    ("inflation_yoy", RATE),
    ("remittances", FLOW),
    ("exports", FLOW),
    ("fdi", FLOW),
    ("reserves", STOCK),
])
def test_our_own_canonical_codes_are_declared(code, esperado):
    """Los conectores tipados emiten códigos que NOSOTROS elegimos, en inglés. Adivinar
    lo que uno mismo definió es absurdo — y la inferencia por patrón está en español
    porque lee planillas del BCRD, así que `public_debt_gdp` caía en `unknown` y perdía
    su lectura. Se declaran."""
    assert infer_nature(None, None, code) == esperado


def test_a_declared_code_wins_over_the_patterns():
    assert infer_nature(None, "cualquier etiqueta", "remittances") == FLOW


def test_english_patterns_cover_foreign_sources():
    """WDI/WGI/IMF publican en inglés: los patrones tienen que leerlos igual."""
    assert infer_nature(None, "Unemployment rate") == RATE
    assert infer_nature(None, "External debt stock") == STOCK
