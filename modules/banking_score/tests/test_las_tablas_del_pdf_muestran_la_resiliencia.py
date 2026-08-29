"""Las tres tablas del PDF dibujan la Resiliencia junto a su banda — y no revientan.

Por qué existe. La banda de Resiliencia se publicaba pegada a la columna «Score», que es el
score GLOBAL: otro número. Un analista externo leyó esa tabla y concluyó que nuestros
umbrales de banda eran arbitrarios. El arreglo agrega la columna que faltaba, pero el
arreglo del PAYLOAD no se ve si la tabla no lo dibuja — y no había un solo test que
ejercitara estas tres tablas.

Además fija el modo de fallo real al agregar una columna, que NO es un crash. Se comprobó:
ReportLab RELLENA los anchos que falten repitiendo el último y no lanza nada. El daño es
silencioso —una columna con el ancho de otra, y si la suma pasa el ancho útil de la página,
la tabla se desborda y se recorta—, así que lo que hay que fijar es que el total entre en
la caja de texto, no que la construcción no reviente.
"""

import pytest

from reportlab.lib.units import inch

from modules.banking_score.reports import pdf_generator as pdf
from shared.products.render import CONTENT_W

_SERIE = [{"corte": "2025-03-31", "score": 68.1, "resiliencia": 75.4, "banda": "Sólida",
           "es_linea_base": True},
          {"corte": "2025-12-31", "score": 71.8, "resiliencia": 75.9, "banda": "Sólida"}]
_CIERRES = [{"anio": 2024, "score": 72.4, "resiliencia": 76.2, "banda": "Sólida"},
            {"anio": 2025, "score": 71.8, "resiliencia": 75.9, "banda": "Sólida"}]

_CASOS = {
    "anio_por_trimestres": (pdf._build_anio_por_trimestres_tables,
                            {"anio": 2025, "serie": _SERIE}),
    "anio_contra_anios": (pdf._build_anio_contra_anios_tables,
                          {"serie_de_cierres": _CIERRES,
                           "variaciones": [{"anio": 2025, "cambio": -0.6}]}),
    "revision_anual": (pdf._build_revision_anual_tables,
                       {"anio": 2025, "serie": _SERIE, "apertura": _SERIE[0],
                        "cierre": _SERIE[-1], "cambio_score": 3.7}),
}


def _tablas(elementos):
    return [e for e in elementos if hasattr(e, "_cellvalues")]


@pytest.fixture
def styles():
    return pdf._get_styles()


@pytest.mark.parametrize("nombre", sorted(_CASOS))
def test_la_tabla_trae_la_columna_resiliencia(nombre, styles):
    fn, payload = _CASOS[nombre]
    tablas = _tablas(fn(payload, styles))
    assert tablas, f"{nombre}: no dibujó ninguna tabla"
    # `_branded_table` envuelve cada celda en un Paragraph: el texto está en `.text`.
    encabezados = [getattr(c, "text", str(c)) for c in tablas[0]._cellvalues[0]]
    assert "Resiliencia" in encabezados, (
        f"{nombre}: la banda se dibuja sin el score que la produce; encabezados={encabezados}")
    assert encabezados.index("Resiliencia") < encabezados.index("Banda"), (
        f"{nombre}: la Resiliencia tiene que ir ANTES de su banda, no suelta: {encabezados}")


@pytest.mark.parametrize("nombre", sorted(_CASOS))
def test_la_tabla_entra_en_el_ancho_de_la_pagina(nombre, styles):
    """Agregar una columna sin rehacer los anchos desborda la caja de texto y la recorta.

    `_argW` NO sirve para detectarlo: ReportLab lo rellena repitiendo el último ancho, así
    que contar celdas contra anchos pasa siempre. Lo que se puede comprobar es el total.
    """
    fn, payload = _CASOS[nombre]
    for t in _tablas(fn(payload, styles)):
        total = sum(t._argW)
        assert total <= CONTENT_W, (
            f"{nombre}: la tabla mide {total / inch:.2f}\" y la caja de texto son "
            f"{CONTENT_W / inch:.2f}\": se desborda y se recortan columnas")


@pytest.mark.parametrize("nombre", sorted(_CASOS))
def test_la_tabla_declara_de_donde_sale_la_banda(nombre, styles):
    """Sin la nota, la columna nueva no explica por qué un score mayor puede dar banda menor."""
    fn, payload = _CASOS[nombre]
    texto = " ".join(getattr(e, "text", "") for e in fn(payload, styles))
    assert "RESILIENCIA" in texto and "eficiencia" in texto, (
        f"{nombre}: la tabla no declara que la banda sale del eje de Resiliencia")
