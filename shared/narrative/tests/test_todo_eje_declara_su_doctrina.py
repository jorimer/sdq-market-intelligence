"""Un eje sin doctrina no falla: cae en «escribe un resumen ejecutivo».

El eje de leyes pasaba `axis="law_intel"` al motor y **no estaba registrado en
`AXIS_DOCTRINE`**. La consecuencia no fue un error: fue que `_uses_cerebro()` devolviera
False, el motor ignorara las plantillas finas del módulo, y `TEMPLATES.get(template) or
TEMPLATES["executive_summary"]` cayera en el genérico. Las cinco secciones del informe
—«Lo que se logró», «Lo que no se logró», «Lo que queda»— salían como cinco resúmenes
ejecutivos con el mismo esqueleto SCQA, cada uno recontando el panorama completo.

Es el modo de falla que este repositorio persigue: **no romperse, servir algo plausible.**
Un producto entero perdió su estructura durante meses y todos los tests estaban verdes.
"""
import ast
import pathlib
import re

import pytest

from shared.narrative.cerebro import AUDIENCE_FRAMES, AXIS_DOCTRINE
from shared.narrative.claude_engine import THIN_TEMPLATES, _uses_cerebro

RAIZ = pathlib.Path(__file__).resolve().parents[3]


def _ejes_declarados_en_los_modulos():
    """Todo `axis=` literal que un módulo le pasa AL MOTOR DE NARRATIVA.

    Se lee el CÓDIGO con `ast` en vez de mantener una lista: una lista a mano envejece en
    cuanto alguien agrega un eje, y el que falte es justo el que se publicará genérico.

    **La condición es `axis` Y `template` en la misma llamada**, que es la firma del motor.
    Barrer todo `axis=` traía `axis="y"` de matplotlib y los `axis=` de los helpers del
    registro de señales —`esg`, `sectoral`—, que no pasan por la doctrina y no tienen por qué
    declararla. Un test que exige lo que no corresponde se desactiva, y desactivado no
    protege de nada.
    """
    encontrados = {}
    for ruta in sorted((RAIZ / "modules").rglob("*.py")):
        if "/tests/" in str(ruta):
            continue
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        except SyntaxError:                                   # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            claves = {kw.arg for kw in nodo.keywords}
            if not {"axis", "template"} <= claves:
                continue
            for kw in nodo.keywords:
                if kw.arg == "axis" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str) and kw.value.value:
                    encontrados.setdefault(kw.value.value, str(ruta.relative_to(RAIZ)))
    return encontrados


EJES = _ejes_declarados_en_los_modulos()


def test_el_barrido_encontro_ejes():
    """Un barrido vacío pasa todos los tests sin proteger nada."""
    assert len(EJES) >= 5, f"el barrido solo encontró {len(EJES)} ejes: revisá el glob"
    assert "y" not in EJES, "el barrido está trayendo `axis='y'` de matplotlib"


@pytest.mark.parametrize("eje", sorted(EJES))
def test_todo_eje_que_el_codigo_usa_TIENE_doctrina(eje):
    assert eje in AXIS_DOCTRINE, (
        f"«{eje}» (en {EJES[eje]}) le pasa `axis` al motor y no tiene doctrina declarada. "
        f"No va a fallar: va a caer en el resumen ejecutivo genérico y sus plantillas "
        f"propias no se leerán nunca.")


@pytest.mark.parametrize("eje", sorted(EJES))
def test_todo_eje_con_doctrina_TIENE_marco_de_audiencia(eje):
    assert eje in AUDIENCE_FRAMES, f"«{eje}» no declara para quién escribe"


def test_las_plantillas_propias_de_un_eje_ENTRAN_por_el_camino_fino():
    """Comprueba la condición real del motor, no que la clave exista en el diccionario."""
    for eje in sorted(EJES):
        propias = [t for t in THIN_TEMPLATES if t.startswith(f"{eje.split('_')[0]}_")]
        for plantilla in propias:
            assert _uses_cerebro(plantilla, eje), (
                f"«{plantilla}» está en THIN_TEMPLATES y el motor NO la usaría para {eje}")


def test_las_plantillas_del_eje_de_leyes_no_piden_un_resumen_ejecutivo():
    """El defecto se veía en el output: cinco secciones con Situación/Complicación/
    Pregunta/Respuesta. Ninguna plantilla propia debe pedir ese molde."""
    for nombre, texto in THIN_TEMPLATES.items():
        if not nombre.startswith("ley_"):
            continue
        for molde in ("SCQA", "resumen ejecutivo", "Resumen Ejecutivo"):
            assert molde not in texto, (
                f"«{nombre}» pide el molde «{molde}»: eso vuelve la sección un resumen más")


def test_la_doctrina_del_eje_de_leyes_dice_lo_que_NO_se_puede_afirmar():
    """La doctrina es el único lugar donde estas reglas alcanzan a TODAS las secciones."""
    d = AXIS_DOCTRINE["law_intel"]
    for regla in ("no se puede incumplir", "no es que se incumpla", "EL FIN ES LA UNIDAD",
                  "COPIÁ LAS RELACIONES"):
        assert re.search(regla, d, re.IGNORECASE), f"la doctrina no declara: «{regla}»"
