"""La fuente que el narrador nombra se COMPUTA del conector, y su atribución de la licencia.

**El defecto, que apareció dos veces en el mismo eje.** El contexto de IA de telecom fijaba
``"source": "INDOTEL (boletín trimestral de indicadores)"`` en una constante y se lo pasaba
al modelo para TODOS los períodos. Pero INDOTEL se congeló en 2022-Q1, sus trimestres se
retiraron de la base y la fuente vigente pasó a ser ITU DataHub: el narrador estuvo
atribuyendo a un emisor que no produjo la cifra. El endpoint tenía el mismo error, se
arregló y quedó su regresión — el contexto de IA no, que es la forma exacta de la doctrina:
son superficies distintas y arreglar una sola deja el documento contradiciéndose.

Al medirlo, **nueve de los `modules/*/ai_context.py` tenían la fuente en un literal**. Cada
uno es un INDOTEL esperando: el día que su emisor cambie, el redactor no se entera.

**La cura.** Una ``Fuente`` no se escribe: se construye DEL CONECTOR, que es lo único que
sabe de dónde sale el dato. Etiqueta y licencia viajan juntas desde el mismo objeto, así que
cambiar el conector cambia las dos, y no hay copia que se quede atrás.

**Y la atribución viene de arriba.** Hay licencias que CONDICIONAN el uso a nombrar la
fuente — la de la UIT es un permiso comercial concedido justamente sobre esa condición. El
texto no lo escribe cada eje: lo computa ``shared.data.licenses`` y este módulo lo baja al
contexto junto con la regla que le dice al modelo que no es opcional. Un eje que mañana
empiece a leer una fuente con esa condición la cumple sin que nadie se acuerde.

Lo vigila ``shared/narrative/tests/test_regla_fuente_computada.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from shared.data.licenses import atribucion_exigida

#: Qué se le dice al modelo cuando la licencia SÍ exige que se nombre a la fuente. Vive en
#: una constante y no incrustada en el dict: un literal partido por ancho de línea deja de
#: existir en el fuente aunque el valor sea correcto.
REGLA_EXIGE_ATRIBUCION = (
    "La fuente de este eje condiciona su uso a que se la nombre: el informe DEBE nombrarla "
    "con el texto exacto de `atribucion_obligatoria`, en la misma sección donde aparecen "
    "sus cifras. No la mandes al final del documento ni la resumas — es una condición de "
    "la licencia, no una cortesía editorial."
)

#: Y cuando no la exige. Se dice explícitamente en vez de omitir la clave: un contexto sin
#: la clave no distingue «no hace falta» de «nadie lo miró».
REGLA_SIN_ATRIBUCION_OBLIGATORIA = (
    "La licencia de esta fuente no condiciona su uso a nombrarla; citala igual como buena "
    "práctica, pero no hay texto obligatorio."
)

_SEPARADOR = " · "


@dataclass(frozen=True)
class Fuente:
    """Un emisor de dato, con lo que hay que decir de él al publicar.

    No se instancia a mano con una licencia escrita: se usa :meth:`de_cliente`, que la toma
    del conector. Escribirla acá sería una copia, y una copia deja de ser la del emisor en
    cuanto alguien corrige el original — que es exactamente lo que pasó con las cuatro
    licencias subdeclaradas del catálogo.
    """

    #: Etiqueta corta del emisor, la del conector (``SIPEN``, ``ITU DataHub``…).
    label: str
    #: Cómo se lo describe en el contexto del narrador: emisor + qué dataset suyo se usa.
    descripcion: str
    #: La licencia declarada por el conector. Clave del registro de licencias.
    license: str
    #: Con qué cadencia publica, cuando el eje la necesita (``annual``, ``quarterly``…).
    cadence: str = ""

    @classmethod
    def de_cliente(cls, cliente: Any, descripcion: str, *, cadence: str = "",
                   label: Optional[str] = None) -> "Fuente":
        """Construye la fuente DESDE el conector: etiqueta y licencia salen de él.

        Es el único constructor que deberían usar los ejes. Ata la procedencia declarada al
        objeto que efectivamente trae el dato, así que cambiar de conector obliga a cambiar
        las dos cosas a la vez y no queda una etiqueta huérfana nombrando al emisor viejo.
        """
        return cls(
            label=label or str(getattr(cliente, "source", "") or ""),
            descripcion=descripcion,
            license=str(getattr(cliente, "license", "") or ""),
            cadence=cadence,
        )

    @property
    def atribucion(self) -> str:
        """El texto que la licencia obliga a publicar, o ``""``. Computado del registro."""
        return atribucion_exigida(self.license)


def bloque_de_atribucion(*fuentes: Fuente) -> Dict[str, str]:
    """Las tres claves de procedencia que todo contexto de IA debería llevar.

    ``source`` (quién produjo el dato), ``atribucion_obligatoria`` (el texto que la licencia
    exige, vacío si no exige ninguno) y ``regla_de_la_atribucion`` (que le dice al modelo
    qué hacer con lo anterior). La regla viaja SIEMPRE con el texto: una lista sin su regla
    se lee como información de contexto y no como obligación.

    Con varias fuentes se concatenan en el orden en que se pasan, y las atribuciones también
    — si dos emisores la exigen, hay que nombrar a los dos.
    """
    vivas = [f for f in fuentes if f is not None]
    textos = [f.atribucion for f in vivas if f.atribucion]
    return {
        "source": _SEPARADOR.join(f.descripcion for f in vivas),
        "atribucion_obligatoria": _SEPARADOR.join(textos),
        "regla_de_la_atribucion": (
            REGLA_EXIGE_ATRIBUCION if textos else REGLA_SIN_ATRIBUCION_OBLIGATORIA),
    }
