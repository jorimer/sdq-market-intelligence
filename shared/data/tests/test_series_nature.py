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
