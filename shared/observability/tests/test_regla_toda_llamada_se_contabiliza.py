"""REGLA ESTRUCTURAL: todo sitio que llame a un modelo contabiliza su gasto.

**El caso que la motivó.** De quince sitios que llamaban al modelo, solo seis contaban su
gasto contra el techo diario. Los nueve que no lo hacían incluían la **visión** —la llamada
más cara de la plataforma, la que ya había costado dinero en relecturas de mazos—, la
extracción de PDF y las tres rutas del agente de investigación, agendado semanalmente.

La consecuencia no era solo un registro incompleto: ``LLM_DAILY_BUDGET_USD`` **no podía
cortar esas rutas nunca**, gastaran lo que gastaran, porque para el contador no existían.
El techo que parecía proteger a toda la plataforma protegía solo a la narrativa.

**Por qué un test y no una lección.** Este repo ya acumuló seis instancias de un guard
presente en un motor y ausente en otro, y la lección escrita no alcanzó ninguna de las
veces. Lo que sí funcionó fue leer el código con ``ast`` y exigir la regla. Funcionó de
verdad: un módulo nuevo escrito por otra sesión el mismo día llegó a ``main`` ya
contabilizando, sin que nadie le recordara la regla.

**El punto ciego que este archivo vino a cerrar.** La primera versión reconocía UNA forma
de llamar, ``…messages.create(``. Hoy es la única que existe en el repo —se verificó—, pero
el día que alguien use respuesta en vivo (``messages.stream``), la API beta, un cliente
asíncrono u otro proveedor, el detector habría pasado en verde mientras ese gasto quedaba
fuera del techo y del registro. Un guard que no ve la forma nueva es peor que no tenerlo:
da una garantía que no cumple. Por eso ahora hay DOS redes.

**La regla.**

1. *Por forma de llamada.* Un módulo con cualquier forma conocida de invocar un modelo
   —Anthropic, OpenAI, Google— tiene que contabilizar.
2. *Por dependencia.* Un módulo que importe un SDK de modelo tiene que contabilizar,
   aunque llame de una forma que no reconozcamos. Esta red no depende de la sintaxis y es
   la que cubre lo que todavía no existe.

Contabilizar es nombrar ``account`` (techo + registro atribuido), ``record_usage`` (solo
techo, anterior al registro) o ``verify_figures`` (contabiliza por dentro). Un sitio que
legítimamente no deba contar se declara en ``EXENTOS`` con su motivo escrito.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Formas de contabilizar. ``account`` hace las dos cosas; ``record_usage`` solo alimenta
#: el techo y se acepta para no forzar una migración masiva; ``verify_figures`` es el juez
#: numérico, que contabiliza su propia llamada por dentro.
_CONTABILIZA = ("account", "record_usage", "verify_figures")

#: Atributos finales de una llamada a un modelo, con el objeto que los antecede. Cubre
#: Anthropic (``messages.create`` / ``messages.stream``, y sus variantes ``beta``),
#: OpenAI (``chat.completions.create``, ``completions.create``, ``responses.create``) y
#: Google (``generate_content``). Se comparan por el par (objeto, método) para no marcar
#: cualquier ``.create(`` de la base de datos.
_FORMAS = {
    ("messages", "create"),
    ("messages", "stream"),
    ("completions", "create"),
    ("completions", "parse"),
    ("responses", "create"),
    ("responses", "stream"),
}

#: Métodos que por sí solos delatan una llamada a un modelo, sin importar el objeto.
_METODOS_SUELTOS = {"generate_content", "generate_content_async", "acompletion"}

#: SDKs de modelo. Importar uno y no contabilizar es la segunda red: no depende de cómo se
#: escriba la llamada, así que cubre las formas que todavía no inventamos.
_SDKS = {"anthropic", "openai", "google.generativeai", "google.genai", "litellm",
         "mistralai", "cohere", "groq"}

#: Sitios que llaman y NO contabilizan, con el motivo. Vacío a propósito: si alguien
#: agrega uno, tiene que escribir por qué.
EXENTOS: dict = {}

# `/.claude/` guarda los worktrees de las sesiones concurrentes: COPIAS del árbol, con los
# mismos archivos bajo otro prefijo. Sin excluirlas, este test denuncia una decena de
# incumplimientos que son los mismos archivos ya conformes, y —peor— el veredicto pasa a
# depender de qué tenga checkouteado otra sesión en el disco de quien lo corre. Un gate
# estructural que falla por el estado local de un tercero enseña a ignorarlo.
#
# (Segunda vez que se agrega: la reescritura de este test se lo llevó por delante. Si lo
# volvés a tocar, la exclusión tiene que sobrevivir — lo vigila el test de abajo.)
_EXCLUIR = ("/tests/", "/.venv/", "/node_modules/", "/.claude/")


def _fuentes():
    for p in sorted(RAIZ.glob("**/*.py")):
        rel = str(p.relative_to(RAIZ))
        if any(x in f"/{rel}" for x in _EXCLUIR):
            continue
        yield rel, p


def llama_a_un_modelo(arbol: ast.AST) -> bool:
    """¿El módulo invoca un modelo por alguna forma conocida?"""
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Call):
            continue
        # Función suelta: `acompletion(...)`, sin objeto delante. Sin esta rama el
        # detector solo veía llamadas con punto, y una biblioteca que exporte funciones
        # de módulo quedaba invisible.
        if isinstance(n.func, ast.Name) and n.func.id in _METODOS_SUELTOS:
            return True
        if not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr in _METODOS_SUELTOS:
            return True
        obj = n.func.value
        if isinstance(obj, ast.Attribute) and (obj.attr, n.func.attr) in _FORMAS:
            return True
    return False


def _es_sdk(nombre: str) -> bool:
    """Compara el nombre COMPLETO con punto, no su primer segmento.

    `import google.generativeai` no se detecta mirando solo «google» —que además marcaría
    a `google.cloud.storage`, que no llama a ningún modelo—. Se compara el prefijo exacto.
    """
    return any(nombre == s or nombre.startswith(s + ".") for s in _SDKS)


def importa_un_sdk(arbol: ast.AST) -> bool:
    """¿El módulo depende de un SDK de modelo, aunque llame de una forma que no vemos?"""
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            if any(_es_sdk(a.name) for a in n.names):
                return True
        elif isinstance(n, ast.ImportFrom) and n.module and _es_sdk(n.module):
            return True
    return False


def contabiliza(arbol: ast.AST) -> bool:
    nombres = {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)
    }
    return bool(nombres & set(_CONTABILIZA))


# ─────────────────────────────────────────────────────────────────────────────
# La regla sobre el repo
# ─────────────────────────────────────────────────────────────────────────────

def test_todo_sitio_que_llama_a_un_modelo_contabiliza_su_gasto():
    incumplen, revisados = [], 0
    for rel, path in _fuentes():
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if not (llama_a_un_modelo(arbol) or importa_un_sdk(arbol)):
            continue
        revisados += 1
        if rel in EXENTOS:
            continue
        if not contabiliza(arbol):
            incumplen.append(rel)

    assert revisados >= 10, (
        "el detector dejó de encontrar los sitios que llaman a un modelo; se volvió "
        f"decorativo (encontró {revisados})"
    )
    assert not incumplen, (
        "Estos sitios llaman a un modelo y NO contabilizan su gasto. No es solo un registro "
        "incompleto: su gasto tampoco cuenta contra LLM_DAILY_BUDGET_USD, así que el techo "
        "diario no puede cortarlos. Agregá `account(...)` tras la llamada, o declaralos en "
        "EXENTOS con su motivo:\n  " + "\n  ".join(incumplen)
    )


def test_la_exencion_exige_motivo_escrito():
    for sitio, motivo in EXENTOS.items():
        assert motivo and len(motivo) > 20, (
            f"{sitio} está exento sin un motivo que se sostenga: escribí por qué esa "
            "llamada no debe contar contra el presupuesto."
        )


def test_la_vision_y_la_extraccion_estan_cubiertas():
    """Los dos caros por unidad, fijados por nombre: son los que más duelen si se caen."""
    for rel in ("modules/brand_intel/ingest/pdf_vision.py",
                "shared/pdf/audited_extractor.py"):
        p = RAIZ / rel
        if not p.exists():
            pytest.skip(f"{rel} ya no existe")
        assert "account(" in p.read_text(encoding="utf-8"), rel


# ─────────────────────────────────────────────────────────────────────────────
# Que el DETECTOR vea lo que dice ver
# ─────────────────────────────────────────────────────────────────────────────
#
# Un detector se prueba con lo que TODAVÍA no está en el repo. Si solo se corriera sobre
# el código actual, pasaría en verde el día que aparezca la forma nueva — que es justo el
# modo de falla que este archivo vino a cerrar.

FORMAS_QUE_DEBE_VER = {
    "anthropic_create": "resp = client.messages.create(model=m, messages=[])",
    "anthropic_stream": "with client.messages.stream(model=m) as s:\n    pass",
    "anthropic_beta": "resp = client.beta.messages.create(model=m, messages=[])",
    "anthropic_async": "resp = await client.messages.create(model=m, messages=[])",
    "openai_chat": "resp = client.chat.completions.create(model=m, messages=[])",
    "openai_responses": "resp = client.responses.create(model=m, input=x)",
    "google": "resp = modelo.generate_content(prompt)",
    "litellm": "resp = await acompletion(model=m, messages=[])",
}


@pytest.mark.parametrize("nombre,fuente", sorted(FORMAS_QUE_DEBE_VER.items()))
def test_el_detector_reconoce_cada_forma_de_llamada(nombre, fuente):
    assert llama_a_un_modelo(ast.parse(fuente)), nombre


@pytest.mark.parametrize("importacion", [
    "import anthropic",
    "from anthropic import Anthropic",
    "import openai",
    "from openai import AsyncOpenAI",
    "import google.generativeai as genai",
    "from litellm import acompletion",
])
def test_la_red_por_dependencia_ve_cualquier_sdk(importacion):
    """Cubre lo que la forma no ve: un SDK importado ya obliga a contabilizar."""
    assert importa_un_sdk(ast.parse(importacion))


@pytest.mark.parametrize("fuente", [
    "db.query(Modelo).create()",            # ORM, no un modelo de lenguaje
    "usuarios.create(nombre='x')",
    "self.responses = []",
    "cache.messages.append(x)",
])
def test_el_detector_no_marca_lo_que_no_es_una_llamada_al_modelo(fuente):
    """Sin esto el guard marcaría medio repo y terminaría desactivado, que es peor."""
    assert not llama_a_un_modelo(ast.parse(fuente))


def test_un_sitio_que_llama_y_no_contabiliza_se_detecta():
    """La prueba negativa: sin ella, «cero incumplimientos» no distingue «está limpio»
    de «el detector no mira nada»."""
    malo = ast.parse("import anthropic\nresp = client.messages.stream(model=m)")
    assert (llama_a_un_modelo(malo) or importa_un_sdk(malo)) and not contabiliza(malo)

    bueno = ast.parse(
        "import anthropic\nresp = client.messages.stream(model=m)\n"
        "account(resp, model=m, purpose='x')"
    )
    assert contabiliza(bueno)


def test_el_barrido_no_lee_los_worktrees_de_otras_sesiones():
    """El glob arranca en la raíz del repo, y las sesiones concurrentes dejan copias
    completas del árbol en `.claude/worktrees/`. Sin excluirlas, este gate denuncia los
    mismos archivos ya conformes vistos bajo otro prefijo — y su veredicto pasa a depender
    de qué tenga checkouteado otra sesión en el disco.

    Ya se perdió una vez en una reescritura del test. Por eso ahora hay un test del test.
    """
    assert "/.claude/" in _EXCLUIR
    assert not [rel for rel, _ in _fuentes() if rel.startswith(".claude/")]
