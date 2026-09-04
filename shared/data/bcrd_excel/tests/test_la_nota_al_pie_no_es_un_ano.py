"""Una nota al pie que menciona un año no es una fila de datos.

`tasa_ocupacion.xls` cierra la hoja «Anual 1960-1984» con dos líneas de prosa: «a) Las
cifras corresponden a la publicación …» y la definición de la tasa. `parse_year` busca
`(19|20)\\d{2}` en CUALQUIER parte del texto, así que la nota producía el período 1986 —una
observación con valor nulo para un año que la serie no publica—.

No fabrica un número (el valor es nulo), pero fabrica un HUECO: declara que 1986 existe y no
tiene dato, cuando lo que pasa es que 1986 no está en el cuadro. «Declarar la brecha» exige
que la brecha sea real.

El corte es por FORMA, no por lista: una celda de más de cuatro palabras es prosa. Las
etiquetas de período del corpus tienen una o dos —«Dic. 2007», «2016 2/», «2011*»,
«Enero 2017», «31/12/2009»— y ninguna llega a cinco.
"""
import pytest

from shared.data.bcrd_excel.periods import parse_year


@pytest.mark.parametrize("celda", [
    "a) Las cifras corresponden a la publicación de 1986 del Banco Central",
    "La tasa de ocupación es igual a la población ocupada entre la PET, 1991",
    "Fuente: Encuesta Nacional de Fuerza de Trabajo, varios años, 2004 en adelante",
])
def test_la_prosa_no_declara_un_periodo(celda):
    assert parse_year(celda) is None, f"«{celda[:40]}…» se leyó como un año"


@pytest.mark.parametrize("celda,esperado", [
    ("Dic. 2007", 2007), ("2016 2/", 2016), ("2011*", 2011), ("Enero 2017", 2017),
    ("31/12/2009", 2009), ("1982.0", 1982), ("Año 2016 (preliminar)", 2016),
    (1982, 1982), (1982.0, 1982),
])
def test_las_etiquetas_de_periodo_del_corpus_siguen_valiendo(celda, esperado):
    assert parse_year(celda) == esperado
