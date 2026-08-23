"""Quién produjo cada período del IDT — y bajo qué licencia. UN solo lugar.

**Por qué existe este módulo.** El eje telecom tiene DOS emisores en la misma serie: el
boletín de INDOTEL, congelado en 2022-Q1 y conservado como histórico, e ITU DataHub, que es
la fuente vigente y anual. Cuál de los dos produjo un punto se deduce del período —con "Q"
es INDOTEL, sin "Q" es la UIT— y esa deducción estaba escrita tres veces: en
``data_signals``, en ``validation_state`` y, mal, en el contexto de IA.

**Lo que costó tenerla escrita tres veces.** El endpoint ``/telecom-intel/score`` etiquetaba
"INDOTEL" fijo; se arregló y quedó su test de regresión (``test_source_label``). El contexto
de IA NO se arregló: siguió diciéndole al modelo «source: INDOTEL (boletín trimestral de
indicadores)» mientras el dato venía de la UIT. Es el patrón que la doctrina ya nombra —
arreglar una superficie sola deja el documento contradiciéndose— y acá dejó al narrador
atribuyendo a un emisor que no produjo la cifra.

**Y desde el 2026-08-18 no es solo un error de procedencia: es un incumplimiento.** La UIT
autorizó por escrito el uso de los datos del DataHub como insumo de productos analíticos
comerciales **con la condición de que se la cite como fuente**. Un informe de telecom que no
la nombre incumple esa condición. Por eso la atribución no se escribe acá: se CONSULTA al
registro de licencias, que es donde vive la obligación.
"""
from __future__ import annotations

from shared.data.indotel_client import INDOTELClient
from shared.data.itu_client import ITUClient
from shared.narrative.atribucion import Fuente

#: Fuente VIGENTE: anual, desde 2000, fresca. Es la serie canónica del IDT.
ITU = Fuente.de_cliente(
    ITUClient, cadence="annual",
    descripcion=("ITU DataHub (Unión Internacional de Telecomunicaciones): penetración "
                 "móvil, banda ancha móvil y fija, y hogares con internet. Serie anual."),
)

#: Fuente MUERTA: el boletín trimestral se congeló en 2022-Q1. Se conserva como histórico y
#: se sigue nombrando porque hay puntos publicados que salieron de ahí.
INDOTEL = Fuente.de_cliente(
    INDOTELClient, cadence="quarterly",
    descripcion=("INDOTEL (boletín trimestral de indicadores), datos abiertos. Serie "
                 "pública congelada en 2022-Q1: histórico, no fuente vigente."),
)


def emisor_del_periodo(period: object) -> Fuente:
    """``'2024'`` → ITU · ``'2022-Q1'`` → INDOTEL.

    La regla es del período y no de una tabla de puntos: un punto nuevo entra con su emisor
    resuelto sin que nadie edite nada. Ante un período vacío o ilegible devuelve la fuente
    VIGENTE, que es la que produce todo lo que se escribe hoy.
    """
    return INDOTEL if "Q" in str(period or "") else ITU
