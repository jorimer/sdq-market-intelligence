"""Un eje NUEVO no puede robarle preguntas a un producto que ya se vende.

El eje de evaluación de leyes entró con un léxico que incluía «ley», «norma», «normativa»,
«articulo» y «decreto». Son palabras que aparecen naturalmente en preguntas de banca,
seguros y pensiones —«¿qué dice la normativa sobre solvencia?»— y con ellas `law` se volvía
eje detectado, lo que significa que el motor le mete el panel de la END como evidencia a una
respuesta de banca. Seis de nueve preguntas de prueba de otros ejes lo activaban.

El daño no es que falle: es que NO falla. La respuesta sale, cita un panel que no viene al
caso y arrastra la cobertura de un eje con 5 de 90 indicadores medidos.

Este test es la regla general, no el parche: vale para cualquier eje que se agregue después.
"""
import re

import pytest

from shared.research.resolve import AXIS_KEYWORDS, _norm

#: Preguntas reales de los productos EN PRODUCCIÓN, elegidas porque usan vocabulario
#: jurídico de forma natural — que es justo donde un eje de leyes invade.
PREGUNTAS_DE_OTROS_PRODUCTOS = [
    ("banking", "¿Qué dice la normativa vigente sobre solvencia de la banca múltiple?"),
    ("banking", "¿Cuál es el artículo de la Ley Monetaria y Financiera sobre encaje legal?"),
    ("insurance", "¿La norma de reservas técnicas cambió para las aseguradoras?"),
    ("pension", "Rentabilidad de las AFP y la ley 87-01 de seguridad social"),
    ("energy", "¿Cómo van las pérdidas del sector eléctrico tras el Pacto Eléctrico?"),
    ("macro", "¿Qué impacto fiscal tiene la reforma normativa de impuestos?"),
    ("trade", "Exportaciones dominicanas por capítulo hacia Estados Unidos"),
]

#: Preguntas que SÍ son de evaluación de instrumentos: el test no debe pasar apagando el eje.
PREGUNTAS_DE_LEYES = [
    "¿Se cumplieron las metas de la END 2030?",
    "Evaluación de la ley 1-12 y sus obligaciones",
    "¿Cuál es el cumplimiento del pacto eléctrico según sus compromisos?",
]


def _activa(eje: str, pregunta: str) -> list:
    q = _norm(pregunta)
    return [kw for kw in AXIS_KEYWORDS.get(eje, ())
            if re.search(r"\b" + re.escape(kw), q)]


@pytest.mark.parametrize("duenio,pregunta", PREGUNTAS_DE_OTROS_PRODUCTOS)
def test_el_eje_de_leyes_no_le_roba_preguntas_a_los_productos_en_produccion(duenio, pregunta):
    hits = _activa("law", pregunta)
    assert not hits, (
        f"la pregunta es de `{duenio}` y activa el eje `law` por {hits}. Un término del "
        "léxico de leyes es demasiado genérico: acotalo a una frase que nombre la "
        "EVALUACIÓN del instrumento, no su tema."
    )


@pytest.mark.parametrize("pregunta", PREGUNTAS_DE_LEYES)
def test_pero_las_preguntas_de_evaluacion_de_leyes_SI_llegan(pregunta):
    """Sin esto, el test de arriba se satisface vaciando el léxico y el eje deja de existir."""
    assert _activa("law", pregunta), f"«{pregunta}» ya no llega al eje de leyes"


def test_ningun_termino_del_lexico_de_leyes_es_una_palabra_suelta_generica():
    """La regla estructural detrás de los dos tests anteriores.

    Una palabra suelta del vocabulario jurídico común no discrimina: aparece en preguntas de
    cualquier sector regulado, que en esta plataforma son casi todos. Para llegar al eje hay
    que nombrar el instrumento o la evaluación, y eso son dos palabras o más.
    """
    genericas = {"ley", "leyes", "norma", "normativa", "articulo", "articulado", "decreto",
                 "reglamento", "legal", "juridico", "resolucion"}
    invasores = [kw for kw in AXIS_KEYWORDS.get("law", ()) if kw in genericas]
    assert not invasores, (
        f"{invasores} son palabras del vocabulario regulatorio común: activan el eje de "
        "leyes en preguntas de banca, seguros y pensiones."
    )
