"""REGLA ESTRUCTURAL: toda excepción con la que el ensamblador VETA tiene manejador en el
router de productos.

El defecto real: ``NarrativeSinRespaldoError`` es un ``RuntimeError`` y no lo atrapaba nadie.
El gate funcionaba —el informe con la cifra inventada NO se entregó, que es lo correcto— pero
el veto salía por la ruta de un error no controlado: 500 sin cuerpo JSON. El front lee
``detail`` y ahí no había nada, así que mostraba "No se pudo cargar el producto". El usuario
veía una FALLA DE CARGA donde hubo una DECISIÓN de no publicar, y sin ninguna pista de cuál.
Verificado en prod (Deep Dive de banca, Q1-2026): 157 s de generación y ~US$1 de modelo para
un error genérico.

Por qué estructural y no una lección escrita: el gemelo de esta excepción
(``NarrativeDegradedError``) SÍ tenía manejador desde el día uno. O sea, la regla ya se
conocía y aun así el segundo gate nació sin ella — es exactamente el patrón "un guard existe
en un motor y falta en el otro", que en este repo ya falló de sobra. El próximo gate que
alguien agregue al ensamblador va a heredar el manejador o va a romper este test.

Alcance declarado (qué queda AFUERA): se leen los ``raise`` DIRECTOS de ``assembler.py``. Una
excepción que el ensamblador propague desde un módulo que llama —hoy ninguna: el sensor de
anonimización levanta ``AnonymizationError`` y el ensamblador la re-lanza él mismo— no la ve
este barrido. Si mañana un sensor veta por su cuenta, hay que ampliar ``_MODULOS_QUE_VETAN``.
"""
import ast
import pathlib
from typing import Optional

import pytest

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
_ASSEMBLER = _RAIZ / "shared" / "products" / "assembler.py"

#: Superficies que entregan un informe y por tanto deben manejar los vetos. El barrido cubría
#: SOLO la ruta de productos, y ese recorte fue el hueco: `router_reports` emite el MISMO
#: documento de cliente (`full_rating` es el SDQ Rating) y llegó a producción con uno de los
#: tres gates. Al escribir el glob de un test estructural hay que preguntarse qué queda afuera
#: — acá lo que quedaba afuera era la mitad del producto.
_SUPERFICIES = (
    _RAIZ / "shared" / "products" / "router.py",
    _RAIZ / "modules" / "banking_score" / "api" / "router_reports.py",
)
_ROUTER = _SUPERFICIES[0]

#: Fuentes cuyos ``raise`` cuentan como veto del ensamblador.
_MODULOS_QUE_VETAN = (_ASSEMBLER,)

#: Dónde viven los gates. Una entrada del ensamblador obliga a manejar los vetos SOLO si
#: llega hasta acá — `assemble_sample_report`, por ejemplo, renderiza la muestra curada sin
#: pasar por los gates, y exigirle manejadores sería pedir código muerto. Se deriva del
#: código en vez de listarlo a mano: si mañana la muestra empieza a pasar por el gate, la
#: obligación aparece sola.
_FUNCION_CON_GATES = "_content_from_snapshot"


def _excepciones_levantadas(path: pathlib.Path) -> set:
    """Nombres de clase de los ``raise X(...)`` directos del módulo."""
    arbol = ast.parse(path.read_text(), filename=str(path))
    out = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Raise) or nodo.exc is None:
            continue
        exc = nodo.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name):
            out.add(exc.id)
        elif isinstance(exc, ast.Attribute):
            out.add(exc.attr)
    return out


def _nombres_de_except(handler: ast.ExceptHandler) -> set:
    tipo = handler.type
    if tipo is None:  # `except:` pelado — atrapa todo
        return {"*"}
    nodos = tipo.elts if isinstance(tipo, ast.Tuple) else [tipo]
    out = set()
    for n in nodos:
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _llamadas(fn: ast.AST) -> set:
    """Nombres invocados dentro de *fn* (por nombre pelado o atributo)."""
    out = set()
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            nombre = (f.id if isinstance(f, ast.Name)
                      else (f.attr if isinstance(f, ast.Attribute) else ""))
            if nombre:
                out.add(nombre)
    return out


def _entradas_gateadas() -> set:
    """Funciones de ``assembler.py`` que alcanzan los gates, directa o transitivamente.

    Punto fijo sobre el grafo de llamadas del módulo: ``assemble_product_report`` no llama al
    gate por sí mismo —llama a ``assemble_product_content``, que sí—, y el test tiene que ver
    esa cadena o dejaría la descarga fuera de la regla."""
    arbol = ast.parse(_ASSEMBLER.read_text(), filename=str(_ASSEMBLER))
    grafo = {n.name: _llamadas(n) for n in ast.walk(arbol)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    alcanzan = {_FUNCION_CON_GATES}
    cambio = True
    while cambio:
        cambio = False
        for nombre, llamadas in grafo.items():
            if nombre not in alcanzan and (llamadas & alcanzan):
                alcanzan.add(nombre)
                cambio = True
    return alcanzan - {_FUNCION_CON_GATES}


def _llama_al_ensamblador(fn: ast.AST) -> bool:
    return bool(_llamadas(fn) & _entradas_gateadas())


def _excepciones_levantadas_en(fn: ast.AST) -> set:
    """Vetos que la propia función levanta — la ruta de reportes corre los gates EN LÍNEA en
    vez de delegarlos al ensamblador, así que no se la detecta por sus llamadas."""
    out = set()
    for nodo in ast.walk(fn):
        if isinstance(nodo, ast.Raise) and nodo.exc is not None:
            exc = nodo.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name):
                out.add(exc.id)
    return out


def _vetos() -> set:
    levantadas = set()
    for m in _MODULOS_QUE_VETAN:
        levantadas |= _excepciones_levantadas(m)
    return levantadas


def _handlers_del_router(fuente: Optional[pathlib.Path] = None):
    """`[(nombre_funcion, {excepciones manejadas})]` de las funciones que entregan un informe.

    Una función CUENTA si llama a una entrada gateada del ensamblador (ruta de productos) o si
    levanta ella misma alguno de los vetos (ruta de reportes, que corre los gates en línea)."""
    fuente = fuente or _ROUTER
    arbol = ast.parse(fuente.read_text(), filename=str(fuente))
    out = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        propios = _excepciones_levantadas_en(nodo)
        if not _llama_al_ensamblador(nodo) and not (propios & _vetos()):
            continue
        manejadas = set()
        for hijo in ast.walk(nodo):
            if isinstance(hijo, ast.Try):
                for h in hijo.handlers:
                    manejadas |= _nombres_de_except(h)
        out.append((nodo.name, manejadas))
    return out


# ── Pruebas NEGATIVAS: el barrido encontró algo ────────────────────────
#
# Sin esto, un `ast` que deje de matchear (un refactor, un rename) daría cero vetos y cero
# handlers, y el test pasaría en verde sin haber mirado nada. Un barrido siempre lleva al
# lado la prueba de que encontró.

def test_el_barrido_encuentra_los_vetos_conocidos():
    levantadas = set()
    for m in _MODULOS_QUE_VETAN:
        levantadas |= _excepciones_levantadas(m)
    assert {"NarrativeDegradedError", "NarrativeSinRespaldoError"} <= levantadas, (
        f"El barrido del ensamblador no ve los vetos conocidos; encontró: {sorted(levantadas)}")


def test_el_grafo_ve_la_entrada_directa_y_la_transitiva():
    gateadas = _entradas_gateadas()
    assert "assemble_product_content" in gateadas, "no ve la entrada DIRECTA al gate"
    assert "assemble_product_report" in gateadas, (
        "no ve la cadena report→content→gate; la descarga quedaría fuera de la regla")
    assert "assemble_sample_report" not in gateadas, (
        "la muestra curada no pasa por los gates; exigirle manejadores es pedir código muerto")


def test_el_barrido_encuentra_los_handlers_del_router():
    handlers = _handlers_del_router()
    assert len(handlers) >= 2, (
        f"Se esperaban al menos las rutas de vista y descarga; encontrado: {handlers}")


# ── La regla ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("superficie", _SUPERFICIES, ids=lambda p: p.name)
def test_toda_superficie_de_entrega_encuentra_sus_funciones(superficie):
    """Prueba negativa por superficie: si el barrido no ve ninguna función que entregue, el
    test de abajo pasa en verde sin haber mirado esa ruta — que es exactamente cómo
    `router_reports` quedó fuera."""
    assert _handlers_del_router(superficie), f"{superficie.name}: el barrido no encontró nada"


def test_todo_veto_del_ensamblador_tiene_manejador_en_el_router():
    levantadas = _vetos()
    faltantes = {}
    for superficie in _SUPERFICIES:
        arbol = ast.parse(superficie.read_text(), filename=str(superficie))
        por_nombre = {n.name: n for n in ast.walk(arbol)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for nombre, manejadas in _handlers_del_router(superficie):
            if "*" in manejadas:
                continue  # `except:` pelado: no deja pasar el veto
            # Qué vetos puede ver ESTA función. Si delega en el ensamblador, le llegan TODOS
            # los que él levanta. Si corre los gates en línea —la ruta de reportes—, solo los
            # que ella misma levanta: exigirle manejar `AnonymizationError`, que nace del
            # sensor del ensamblador y esa ruta no invoca, sería pedir código muerto. Es el
            # mismo criterio que excluye a la muestra curada.
            fn = por_nombre.get(nombre)
            alcanzables = (levantadas if fn is not None and _llama_al_ensamblador(fn)
                           else _excepciones_levantadas_en(fn) & levantadas)
            sin_manejar = alcanzables - manejadas
            if sin_manejar:
                faltantes[f"{superficie.name}:{nombre}"] = sorted(sin_manejar)
    assert not faltantes, (
        "Estas rutas llaman al ensamblador y no manejan vetos que él levanta — van a salir "
        f"como 500 genérico y el usuario leerá 'no se pudo cargar': {faltantes}")


#: Los TRES gates de entrega, por el nombre con que se los invoca. Que una superficie MANEJE
#: la excepción no prueba que CORRA el gate: el defecto real de `router_reports` no fue un
#: handler faltante sino un gate ausente, y la regla de arriba —que solo mira handlers— pasa
#: en verde contra ese código. Fueron necesarias las dos.
_GATES = {
    "degraded_sections": "sección hueca (degradación)",
    "secciones_con_cifra_sin_respaldo": "cifra sin respaldo",
    "acumulando": "relación invertida (acumulador por generación)",
}


@pytest.mark.parametrize("superficie", _SUPERFICIES, ids=lambda p: p.name)
def test_toda_superficie_de_entrega_corre_los_TRES_gates(superficie):
    """La regla que el hueco real pedía.

    `router_reports` emite el SDQ Rating y llegó a producción con UNO de los tres gates —los
    otros dos vivían solo en la ruta de productos—. Una superficie los corre ella misma, o
    delega en el ensamblador, que los corre por ella; lo que no puede es no tenerlos.
    """
    texto = superficie.read_text()
    arbol = ast.parse(texto, filename=str(superficie))
    invocados = {n for nodo in ast.walk(arbol)
                 if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                 for n in _llamadas(nodo)}
    delega = bool(invocados & _entradas_gateadas())
    if delega:
        invocados |= {n for nodo in ast.walk(ast.parse(_ASSEMBLER.read_text()))
                      if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                      for n in _llamadas(nodo)}
    faltan = {g: q for g, q in _GATES.items() if g not in invocados}
    assert not faltan, (
        f"{superficie.name} entrega informes sin correr estos gates: {faltan}. Corrélos ahí o "
        "delegá en el ensamblador, que los corre.")


@pytest.mark.parametrize("ruta", ["get_product_report", "get_product_pdf"])
def test_el_veto_por_cifra_sin_respaldo_se_maneja_en_ambas_superficies(ruta):
    """La vista in-app y la descarga comparten el gate: si una sola lo tradujera, el mismo
    informe respondería un mensaje en pantalla y un 500 al descargarlo."""
    manejadas = dict(_handlers_del_router()).get(ruta)
    assert manejadas is not None, f"'{ruta}' ya no llama al ensamblador; actualizá el test"
    assert "NarrativeSinRespaldoError" in manejadas
