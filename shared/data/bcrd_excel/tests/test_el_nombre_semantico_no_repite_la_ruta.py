"""El nombre que devuelve el modelo puede venir ya calificado: no se le antepone dos veces.

Cuando una fila se desempata por coordenada (`_rNN`) se le pide al modelo la lectura de un
analista. El modelo suele responder la RUTA COMPLETA —«Cuenta Corriente > Balanza de Bienes y
Servicios > Balanza de Bienes > Importaciones > Nacionales»— y el código la pegaba detrás de
la cabeza del código viejo, que ya traía esa misma ruta. Salía:

    bcrd.xls.bpagos_6.cuenta_corriente.balanza_de_bienes_y_servicios.balanza_de_bienes.
    cuenta_corriente.balanza_de_bienes_y_servicios.balanza_de_bienes.importaciones.nacionales

La serie es correcta y el dato también; el código es impresentable y, sobre todo, es
INESTABLE: depende de cuánta ruta haya decidido incluir el modelo esa vez. Un código de serie
es un contrato con la base — se persiste, se cita y se consulta por él.

La regla: si la cabeza del código ya termina con los primeros niveles del nombre propuesto,
esos niveles no se repiten.
"""
from shared.data.bcrd_excel.engine import _pegar_sin_repetir


def test_no_repite_la_ruta_que_la_cabeza_ya_trae():
    head = "bcrd.xls.bpagos_6.cuenta_corriente.balanza_de_bienes_y_servicios.balanza_de_bienes"
    slug = "cuenta_corriente.balanza_de_bienes_y_servicios.balanza_de_bienes.importaciones.nacionales"
    assert _pegar_sin_repetir(head, slug) == f"{head}.importaciones.nacionales"


def test_un_solapamiento_parcial_tambien_se_recorta():
    assert _pegar_sin_repetir("a.b.c", "c.d") == "a.b.c.d"


def test_sin_solapamiento_pega_entero():
    assert _pegar_sin_repetir("a.b", "c.d") == "a.b.c.d"


def test_el_nombre_repetido_entero_no_borra_la_hoja():
    """Si el modelo devuelve exactamente la ruta de la cabeza y nada más, el código queda
    como estaba: mejor un `_rNN` honesto que una serie sin hoja."""
    assert _pegar_sin_repetir("a.b.c", "a.b.c") == "a.b.c"
