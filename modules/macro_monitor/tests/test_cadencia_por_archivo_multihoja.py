"""Un archivo con varias hojas publica varias cadencias, y eso no es un parse roto.

`tasa_ocupacion.xls` trae «Anual 1960-1984», «Anual 1991-2016» y «Semestral 2000-2016»: la
entrada canónica declara UNA cadencia y el archivo produce dos formas de período. El
detector marcaba discrepancia porque exigía que la declarada fuera la ÚNICA presente.

La señal que importa —el eje temporal leído mal— es que la cadencia declarada NO APAREZCA en
ninguna serie del archivo. Que aparezca junto a otras significa que el registro apunta a una
de las hojas y las demás publican otro corte, que es lo normal en este corpus; la propia
`series_cadence` ya lo dice: «la declaración del canónico es por SERIE, pero se ingiere por
ARCHIVO».

Lo que NO se pierde con esto: una serie cuyos períodos mezclan formas —anual y mensual en la
misma serie— la caza el criterio de formas mezcladas, que es por serie y no por archivo, y
es el instrumento más filoso de los dos.
"""
from shared.data.series_cadence import discrepancia_de_cadencia


def test_la_declarada_ausente_sigue_siendo_discrepancia():
    d = discrepancia_de_cadencia("trimestral", ["1960", "1961", "2016-04"])
    assert d and "quarterly" in d


def test_la_declarada_presente_entre_otras_no_lo_es():
    assert discrepancia_de_cadencia("anual", ["1960", "1961", "2016-04"]) is None


def test_sin_declaracion_no_hay_nada_que_contrastar():
    assert discrepancia_de_cadencia(None, ["2016-04"]) is None


def test_la_coincidencia_exacta_sigue_pasando():
    assert discrepancia_de_cadencia("mensual", ["2016-04", "2016-05"]) is None
