"""El andamiaje no ceba el registro de comentarista.

**La causa raíz ya estaba documentada y la repetí.** El estándar de tono del dueño exige
títulos «descriptivos y sobrios» y prohíbe los giros de comentarista; vive en
`cerebro.REGISTER_NEUTRO` y lo reciben todas las plantillas de la ruta cerebro. Aun así, el
anuario del sistema de 2023 salió con:

    ## La fractura estructural: banca múltiple vs. el resto
    ## Trayectoria intrayear: el deterioro fue temprano
    «La cadena causal aquí no es uniforme…»  ·  «El hallazgo central…»

No fue que el registro fallara: fue que MI PLANTILLA lo pisaba. Decía «es el **hallazgo
estructural** del año y **merece el centro**» y «ESO es el **hallazgo** y va al frente», y el
modelo devolvió el vocabulario que le di. Es exactamente lo que la memoria del estándar ya
registraba: «CAUSA RAÍZ del leak: nuestro propio andamiaje cebaba al modelo».

Por eso la regla se verifica sobre las PLANTILLAS, no sobre la salida: una salida se corrige
regenerando, un andamiaje cebado vuelve a producir lo mismo cada vez.
"""
import pytest

from shared.narrative.claude_engine import THIN_TEMPLATES

#: Las plantillas de la línea anual. Si se agrega otra, va acá.
ANUALES = ("anuario_sistema", "anio_del_sistema", "revision_anual", "revision_anual_mercado")

#: Vocabulario que CEBA el registro de comentarista. No es que la palabra esté prohibida en un
#: informe: es que ponerla en la INSTRUCCIÓN se la devuelve al modelo amplificada.
CEBOS = (
    "hallazgo estructural",
    "merece el centro",
    "ESO es el hallazgo",
    "va al frente",
    "la cadena que importa",
    "lo que más importa",
)

#: Anglicismos casuales que el registro neutro prohíbe y que no deben aparecer en el prompt.
ANGLICISMOS = ("intrayear", "insight de", "driver", "upside", "downside")


def test_las_plantillas_anuales_existen():
    """Prueba negativa: un rename dejaría este test verde sin mirar nada."""
    faltan = [t for t in ANUALES if t not in THIN_TEMPLATES]
    assert not faltan, f"el barrido apunta a plantillas que ya no existen: {faltan}"


@pytest.mark.parametrize("plantilla", ANUALES)
def test_la_plantilla_no_ceba_vocabulario_de_comentarista(plantilla):
    t = THIN_TEMPLATES[plantilla]
    presentes = [c for c in CEBOS if c.lower() in t.lower()]
    assert not presentes, (
        f"{plantilla} ceba al modelo con {presentes}. El modelo devuelve el vocabulario que le "
        "damos: «hallazgo estructural» en la instrucción produjo «La fractura estructural» "
        "como título. Describí QUÉ desarrollar, no con qué palabras.")


@pytest.mark.parametrize("plantilla", ANUALES)
def test_la_plantilla_no_introduce_anglicismos(plantilla):
    t = THIN_TEMPLATES[plantilla]
    # Se admiten cuando la instrucción los PROHÍBE explícitamente («no 'intrayear'»).
    presentes = [a for a in ANGLICISMOS
                 if a.lower() in t.lower() and f"no '{a}'" not in t and f"no «{a}»" not in t]
    assert not presentes, f"{plantilla} introduce anglicismos casuales: {presentes}"


@pytest.mark.parametrize("plantilla", ("anuario_sistema", "anio_del_sistema", "revision_anual"))
def test_las_plantillas_QUE_LLEVAN_TITULOS_los_piden_sobrios(plantilla):
    """El contrapeso de quitar el cebo: sin pedir títulos sobrios, el modelo elige el registro
    por su cuenta y el estándar queda a merced de la suerte."""
    t = THIN_TEMPLATES[plantilla]
    assert "SOBRIOS" in t, f"{plantilla} no pide títulos descriptivos y sobrios"


def test_el_registro_neutro_sigue_llegando_a_estas_plantillas():
    """Sin esto, la regla de arriba se satisface y el estándar igual no se aplica: las
    plantillas tienen que ir por la ruta cerebro, que es la que adjunta el registro."""
    from shared.narrative.claude_engine import _uses_cerebro

    for t in ANUALES:
        assert _uses_cerebro(t, "banking"), f"{t} no recibe REGISTER_NEUTRO"
