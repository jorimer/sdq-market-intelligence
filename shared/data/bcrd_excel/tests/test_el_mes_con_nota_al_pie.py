"""Un mes con la llamada a nota pegada al nombre sigue siendo ese mes.

La serie de Tasa de Política Monetaria rotula dos filas «Feb1» y «Mar2»: el BCRD pega la
llamada a pie de página al nombre del mes, sin espacio ni barra. `parse_month` no las
reconocía y esas dos filas se descartaban — no fallaba nada, la serie salía con 271
observaciones en vez de 273 y con **dos huecos internos**.

Los huecos no eran en cualquier parte: **febrero de 2013** y **marzo de 2020**, los dos meses
en que el BCRD movió la tasa (0,05 → 0,0425 en 2013; 0,045 → 0,035 al empezar la pandemia).
Justo el dato que un modelo con rezagos necesita, y el que un ojo no echa de menos.

Lo encontró la aserción de continuidad de T-PS-4 en su primera corrida.
"""
import pytest

from shared.data.bcrd_excel.periods import parse_month


@pytest.mark.parametrize("celda,esperado", [
    ("Feb1", 2), ("Mar2", 3), ("Ene3", 1), ("Dic.1", 12), ("Sep 2", 9),
    ("Septiembre1", 9), ("Feb1 2013", 2),
])
def test_la_llamada_a_nota_no_borra_el_mes(celda, esperado):
    assert parse_month(celda) == esperado


@pytest.mark.parametrize("celda", ["T1", "1T", "Trim1", "2013", "Total", "", "1", "Q1"])
def test_lo_que_no_es_un_mes_sigue_sin_serlo(celda):
    assert parse_month(celda) is None


@pytest.mark.parametrize("celda,esperado", [
    ("Enero", 1), ("Dic.", 12), ("ene", 1), ("Septiembre", 9), ("Dic. 2007", 12),
])
def test_las_grafias_de_siempre_no_se_tocan(celda, esperado):
    assert parse_month(celda) == esperado
