"""Parline — parser del Senado (lógica pura, sin red).

La página trae VARIAS tablas con porcentajes, así que el riesgo real no es no encontrar
nada: es leer la tabla equivocada y publicarla como composición del Senado.
"""
import pytest

from shared.data.ipu_parline_client import ParlineUnavailable, parse_serie

_PAGINA = """
<div>Otra tabla<td>1999-01</td><td>99.9%</td></div>
<h3>Historical data for Percentage of women</h3>
<table>
  <tr><td>2024-05</td><td>12.5%</td></tr>
  <tr><td>2020-07</td><td>12.5%</td></tr>
  <tr><td>2010-05</td><td>9.4%</td></tr>
</table>
"""


def test_se_ancla_en_el_rotulo_y_no_en_una_posicion():
    """La tabla de arriba tiene un 99,9% que no es esto. Un índice fijo la tomaría."""
    assert parse_serie(_PAGINA) == [(2010, 9.4), (2020, 12.5), (2024, 12.5)]


def test_sin_el_rotulo_falla_en_vez_de_leer_otra_tabla():
    """Un cambio de layout tiene que dejar la serie vacía y VISIBLE, no producir la serie
    de otra cosa con la misma forma."""
    with pytest.raises(ParlineUnavailable, match="Historical data"):
        parse_serie("<div>Otra tabla<td>1999-01</td><td>99.9%</td></div>")


def test_descarta_porcentajes_imposibles():
    p = _PAGINA.replace("<td>12.5%</td>", "<td>150.0%</td>", 1)
    assert (2024, 12.5) not in parse_serie(p)


def test_un_solo_valor_por_ano():
    """Hay años con dos entradas (elección y actualización posterior). Dos puntos del mismo
    año producirían una trayectoria con un escalón que no ocurrió."""
    p = _PAGINA.replace("<tr><td>2010-05</td><td>9.4%</td></tr>",
                        "<tr><td>2010-08</td><td>9.4%</td></tr>"
                        "<tr><td>2010-05</td><td>8.0%</td></tr>")
    s = dict(parse_serie(p))
    assert s[2010] == 9.4, "debe ganar la primera fila, que es la más reciente del año"
