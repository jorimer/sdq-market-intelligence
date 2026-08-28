"""Los nombres de campo del contexto no se imprimen en el documento del cliente.

**El caso.** Una Revisión Anual salió a producción diciendo:

    «Los campos `vs_su_tipo`, `vs_el_sistema` y `es_idiosincratico` llegan en null en el
     contexto disponible…»

El modelo hizo lo correcto —declarar la brecha en vez de rellenarla, que es la doctrina— pero
en el registro equivocado: nombró las claves del JSON y la palabra «null» en un documento que
se vende. La instrucción decía «un campo en null significa que faltó el dato: decilo», y el
modelo lo dijo LITERALMENTE.

La causa de fondo fue otra —el contraste se había apagado por una clave renombrada— pero eso
no excusa el registro: cuando un dato falte de verdad, el informe tiene que decirlo en prosa.

Alcance declarado: se vigila la INSTRUCCIÓN, no la salida. Un test sobre el texto generado
exigiría generar —cien segundos y una llamada al modelo por corrida— y fallaría por
temperatura, no por regresión.
"""
from __future__ import annotations

import pytest

from shared.narrative.claude_engine import THIN_TEMPLATES

#: Plantillas que sirven bloques cuyos campos pueden venir vacíos y que por eso instruyen
#: sobre cómo declararlo. Son las que pueden inducir al modelo a nombrar la clave.
PLANTILLAS_CON_CAMPOS_OPCIONALES = ("revision_anual_mercado", "revision_anual",
                                    "anio_por_trimestres")


def test_el_barrido_encuentra_las_plantillas():
    """Prueba negativa: una plantilla renombrada dejaría el barrido sin objeto y el test
    pasaría sin haber leído nada."""
    for nombre in PLANTILLAS_CON_CAMPOS_OPCIONALES:
        assert nombre in THIN_TEMPLATES, f"la plantilla '{nombre}' ya no existe"


@pytest.mark.parametrize("nombre", PLANTILLAS_CON_CAMPOS_OPCIONALES)
def test_la_plantilla_que_menciona_null_explica_como_decirlo(nombre):
    """No basta con pedir que lo declare: hay que decir EN QUÉ REGISTRO.

    «Un campo en null significa que faltó el dato: decilo» produjo exactamente eso — el
    modelo lo dijo, con el nombre del campo y la palabra «null» adentro.
    """
    texto = THIN_TEMPLATES[nombre]
    if "null" not in texto:
        pytest.skip("esta plantilla no habla de campos vacíos")
    assert "PROSA" in texto or "prosa" in texto, (
        f"'{nombre}' pide declarar un campo vacío pero no dice cómo: el modelo va a nombrar "
        "la clave del contexto en el documento del cliente.")
    assert "Nunca nombres los campos" in texto or "no nombres" in texto.lower(), (
        f"'{nombre}' no prohíbe explícitamente nombrar los campos del contexto")
