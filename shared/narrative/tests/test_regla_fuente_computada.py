"""REGLA ESTRUCTURAL: la fuente que el narrador nombra se COMPUTA del conector.

**El caso, y cuánto tardó en verse.** El contexto de IA del eje telecom declaraba
``"source": "INDOTEL (boletín trimestral de indicadores)"`` en un literal, y se lo pasaba al
modelo para todos los períodos. INDOTEL se congeló en 2022-Q1, sus trimestres se retiraron de
la base y la fuente vigente pasó a ser ITU DataHub: durante ese tiempo el narrador atribuyó
cada cifra a un emisor que no la produjo. El endpoint tenía el mismo defecto, se arregló, y
quedó su test de regresión — el contexto de IA no, que es la doctrina de siempre: son
superficies distintas y arreglar una sola deja el documento contradiciéndose.

**Y no era uno.** Al medirlo aparecieron NUEVE módulos con la fuente en literal. Cada uno era
lo mismo esperando a que su emisor cambiara. Por eso esto es un test y no una lección: la
lección ya estaba escrita y el defecto igual se repartió por el repo.

**Desde el 2026-08-18 además puede ser un incumplimiento.** La UIT autorizó el uso comercial
de ITU DataHub a condición de citarla. Una atribución escrita a mano se pierde en la primera
reescritura; computada del registro de licencias, no.

**Qué exige.**

1. Ningún ``modules/*/ai_context.py`` pone un literal como valor de ``source`` / ``fuente`` /
   ``sources`` / ``emisor``. La procedencia sale de una :class:`~shared.narrative.atribucion.Fuente`.
2. Toda ``Fuente`` se construye con ``de_cliente(...)``, que toma etiqueta y licencia DEL
   CONECTOR. El constructor directo con una licencia escrita a mano vuelve a crear la copia
   que se desincroniza — es el defecto que dejó cuatro licencias subdeclaradas en el catálogo.

**Qué NO exige.** Que todo eje tenga atribución obligatoria: la mayoría de las licencias del
catálogo no la condicionan, y varias están sin verificar. Lo que garantiza es que el día que
alguien verifique una y encuentre esa condición, el texto llegue solo al narrador.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
CONTEXTOS = sorted((RAIZ / "modules").glob("*/ai_context.py"))

#: Claves cuyo valor es una declaración de procedencia. Un literal acá es la fuente escrita
#: a mano, que es lo que envejece sin que nadie lo note.
_CLAVES = {"source", "fuente", "sources", "emisor"}

#: El constructor que ata la fuente al conector. El directo (`Fuente(...)`) queda para
#: `shared/narrative/atribucion.py`, que es quien lo define.
_CONSTRUCTOR = "de_cliente"


def _literales_de_procedencia(arbol: ast.AST):
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if (isinstance(k, ast.Constant) and k.value in _CLAVES
                    and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                yield n.lineno, k.value, v.value


def _fuentes_construidas(arbol: ast.AST):
    """Cada ``Fuente(...)`` / ``Fuente.de_cliente(...)`` con la forma en que se llamó."""
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "Fuente":
            yield n.lineno, f.attr, n
        elif isinstance(f, ast.Name) and f.id == "Fuente":
            yield n.lineno, "", n


def test_el_detector_encuentra_los_contextos():
    """Sin esto, mover o renombrar los ai_context volvería decorativa la regla."""
    assert len(CONTEXTOS) >= 8, f"el detector se volvió decorativo: {CONTEXTOS}"


@pytest.mark.parametrize("path", CONTEXTOS, ids=lambda p: p.parent.name)
def test_ningun_contexto_escribe_su_fuente_a_mano(path):
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    malos = list(_literales_de_procedencia(arbol))
    assert not malos, (
        f"{path.relative_to(RAIZ)} declara su procedencia con un literal:\n" +
        "\n".join(f"    línea {ln}: {clave}={val!r}" for ln, clave, val in malos) +
        "\nUna fuente escrita a mano sobrevive al cambio de emisor: el eje telecom siguió "
        "diciéndole «INDOTEL» al narrador durante años después de pasarse a la UIT.\n"
        "Declará la fuente con `Fuente.de_cliente(<Cliente>, descripcion=...)` y volcala al "
        "contexto con `**bloque_de_atribucion(...)`, que además baja la atribución que la "
        "licencia exija."
    )


@pytest.mark.parametrize("path", CONTEXTOS, ids=lambda p: p.parent.name)
def test_toda_fuente_se_construye_del_conector(path):
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    directos = [ln for ln, ctor, _ in _fuentes_construidas(arbol) if ctor != _CONSTRUCTOR]
    assert not directos, (
        f"{path.relative_to(RAIZ)} construye una `Fuente` a mano en las líneas {directos}. "
        f"Usá `Fuente.{_CONSTRUCTOR}(<Cliente>, ...)`: la etiqueta y la licencia salen del "
        f"objeto que trae el dato, y así cambiar de conector las cambia juntas. Escribir la "
        f"licencia acá es una copia, y una copia deja de ser la del emisor en cuanto alguien "
        f"corrige el original — así entraron cuatro licencias subdeclaradas al catálogo."
    )


def test_los_ejes_cableados_no_se_descablean_en_silencio():
    """Contrapeso del `skip` de más abajo.

    `test_el_bloque_de_procedencia_viaja_entero` se saltea los contextos que no declaran
    fuentes — legítimo, no todos tienen una. Pero si alguien quitara el helper de todos, esa
    prueba pasaría entera en verde a fuerza de saltearse: un barrido que no encuentra nada no
    protege nada. Este test fija el piso.
    """
    cableados = [p.parent.name for p in CONTEXTOS
                 if "bloque_de_atribucion" in p.read_text(encoding="utf-8")]
    assert len(cableados) >= 8, (
        f"solo {len(cableados)} ejes computan su fuente ({cableados}); eran 9 al cerrar la "
        f"regla. Si un eje dejó de declararla, su narrador volvió a nombrar lo que diga un "
        f"literal.")


def test_al_menos_un_eje_lleva_atribucion_obligatoria():
    """Si NINGUNO la llevara, el mecanismo estaría cableado y muerto.

    El caso vivo es telecom: la UIT condiciona el permiso comercial a que se la cite.
    """
    from modules.telecom_intel.ai_context import telecom_ai_context

    ctx = telecom_ai_context({"telecom_score": 60.0, "band": "B", "dimensions": {}}, "2024")
    assert ctx["atribucion_obligatoria"], "el mecanismo no está llegando a ningún contexto"


@pytest.mark.parametrize("path", CONTEXTOS, ids=lambda p: p.parent.name)
def test_el_bloque_de_procedencia_viaja_entero(path):
    """Quien usa el helper lo usa completo: la regla siempre acompaña al texto.

    Volcar solo `atribucion_obligatoria` dejaría al modelo leyendo la atribución como un
    dato más del contexto en vez de como una obligación — que es la diferencia entre que
    aparezca en el informe y que no.
    """
    texto = path.read_text(encoding="utf-8")
    if "bloque_de_atribucion" not in texto:
        pytest.skip(f"{path.parent.name} no declara fuentes con el helper")
    assert "**bloque_de_atribucion(" in texto, (
        f"{path.relative_to(RAIZ)} usa `bloque_de_atribucion` sin desempaquetarlo con `**`: "
        f"la regla y el texto de atribución tienen que entrar juntos al contexto.")
