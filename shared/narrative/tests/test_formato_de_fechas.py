"""Escribir meses y fechas en castellano: los conectores sabían LEERLAS, nadie ESCRIBIRLAS."""
import pytest

from shared.narrative.formato import fecha_larga_es, mes_largo_es, mes_siguiente


@pytest.mark.parametrize("periodo,esperado", [
    ("2026-06", "junio de 2026"),
    ("2026-01", "enero de 2026"),
    ("2026-12", "diciembre de 2026"),
])
def test_un_periodo_mensual_se_escribe_con_su_nombre(periodo, esperado):
    assert mes_largo_es(periodo) == esperado


@pytest.mark.parametrize("periodo", ["2026", "2026-Q2", "2026-13", "", None, "junio"])
def test_un_periodo_que_NO_es_mensual_no_recibe_nombre_de_mes(periodo):
    """Darle nombre de mes a un trimestre inventaría una precisión que el dato no tiene."""
    assert mes_largo_es(periodo) is None


def test_una_fecha_iso_se_escribe_larga():
    assert fecha_larga_es("2026-07-21") == "21 de julio de 2026"
    assert fecha_larga_es("2026-07-21T12:39:08.996340") == "21 de julio de 2026"


@pytest.mark.parametrize("crudo", ["", None, "21/07/2026", "2026-13-01", "ayer"])
def test_una_fecha_ilegible_no_se_escribe(crudo):
    assert fecha_larga_es(crudo) is None


def test_el_mes_siguiente_cruza_el_anio():
    assert mes_siguiente("2026-06") == "2026-07"
    assert mes_siguiente("2026-12") == "2027-01"
    assert mes_siguiente("2026") is None
