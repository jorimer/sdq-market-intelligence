"""Un test que registra operaciones deja `OPERATIONS` como lo encontró.

**El defecto que lo obligó.** `register()` de un módulo de operaciones construye `Operation`
NUEVAS y reemplaza las que ya estaban. Las viejas llevaban los `triggers` que
`shared.alerts.motor.enganchar_cascada()` les agregó al arrancar la app; las nuevas no. Un
test que llama a `register()` sin restaurar el registro saca en silencio esas operaciones de
la cascada al barrido de alertas, y el que se pone rojo es OTRO test, en otro directorio:

    pytest shared/operations/tests/ shared/alerts/tests/test_cascada.py -q
    → FAILED test_toda_operacion_NO_excluida_despierta_el_barrido
      operaciones sin cascada: ['bcrd-ied-sync', 'bcrd-sectores-sync', ...]

CI no lo veía porque, en orden alfabético, `shared/alerts` corre antes que
`shared/operations`. Cualquier cambio de orden —un subset, `-p randomly`, un archivo nuevo—
lo destapa. Apareció dos veces (#1186 lo arregló en sus propios tests, y
`test_cascades.py` lo seguía teniendo): la lección escrita no alcanza.

**Qué se exige.** Toda llamada, desde un test, a una función que registra operaciones
—`register_operation` o cualquier función del código que la llame, de forma transitiva—
tiene que estar protegida por una de estas tres cosas:

1. un `try` cuyo `finally` restaura el registro (`OPERATIONS.update(...)`);
2. estar dentro de un fixture que lo restaura;
3. estar en una función que pide (por parámetro o `usefixtures`) un fixture que lo restaura,
   definido en el mismo archivo o en un `conftest.py` de un directorio ancestro.

Se resuelve QUÉ función se llama siguiendo los imports, no se busca el nombre `register`:
`alerts_producer.register()` engancha un productor de alertas, no toca `OPERATIONS`, y un
guard que lo marcara enseñaría a ignorar el guard.
"""
import ast
import pathlib
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Set

RAIZ = pathlib.Path(__file__).resolve().parents[3]
CARPETAS = ("modules", "shared", "app")

#: Se compara contra la ruta RELATIVA a RAIZ: dentro de un worktree la absoluta contiene
#: «.claude/worktrees» y excluiría todo (ver `shared/tests/test_toda_ruta_recibe_su_path.py`).
EXCLUIDOS = (".venv", "node_modules", "/.git/", ".claude/worktrees", "__pycache__")

SEMILLA = "shared.operations.service.register_operation"

#: `"ruta/relativa.py::funcion"` → por qué ESA llamada puede registrar sin restaurar.
#: Vacío a propósito: hasta hoy ningún caso lo justificó. Una entrada que ya no corresponde a
#: una llamada desprotegida es rancia y hace fallar `test_ninguna_EXCEPCION_esta_rancia`.
EXCEPCIONES: Dict[str, str] = {}

#: Los tres casos que el barrido tiene que ver. Si deja de encontrarlos, el verde no protege.
CONOCIDOS = {
    ("shared/operations/tests/test_cascades.py", "test_sector_intel_cascade_graph_is_wired"),
    ("modules/banking_score/tests/test_sib_backfill_via_consola.py",
     "test_la_operacion_esta_registrada_bajo_demanda"),
    ("modules/macro_monitor/tests/test_barrido_excel_via_consola.py",
     "test_las_operaciones_estan_registradas_bajo_demanda"),
}


class Sitio(NamedTuple):
    archivo: str
    linea: int
    funcion: str
    destino: str
    protegido: bool


def _archivos() -> Iterator[pathlib.Path]:
    for carpeta in CARPETAS:
        for f in (RAIZ / carpeta).rglob("*.py"):
            rel = "/" + f.relative_to(RAIZ).as_posix()
            if not any(x in rel for x in EXCLUIDOS):
                yield f


def _es_test(rel: str) -> bool:
    nombre = rel.rsplit("/", 1)[-1]
    return "/tests/" in "/" + rel or nombre.startswith("test_") or nombre == "conftest.py"


def _modulo(rel: str) -> str:
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


def _parse(f: pathlib.Path) -> Optional[ast.Module]:
    try:
        return ast.parse(f.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):              # pragma: no cover - defensivo
        return None


def _imports(arbol: ast.AST) -> Dict[str, str]:
    """Alias local → nombre punteado. Incluye los imports dentro de funciones: los tests
    importan el módulo de operaciones adentro del cuerpo a menudo."""
    tabla: Dict[str, str] = {}
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    tabla[a.asname] = a.name
                else:
                    raiz = a.name.split(".")[0]
                    tabla[raiz] = raiz
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                tabla[a.asname or a.name] = f"{n.module}.{a.name}"
    return tabla


def _destino(func: ast.expr, imports: Dict[str, str], modulo: str) -> Optional[str]:
    partes: List[str] = []
    while isinstance(func, ast.Attribute):
        partes.append(func.attr)
        func = func.value
    if not isinstance(func, ast.Name):
        return None
    base = imports.get(func.id, f"{modulo}.{func.id}" if not partes else func.id)
    return ".".join([base, *reversed(partes)])


def _registra(destino: Optional[str], registradores: Set[str]) -> bool:
    if destino is None:
        return False
    # Una re-exportación (`from shared.operations import register_operation`) sigue siendo
    # la semilla: se reconoce por el nombre final.
    return destino in registradores or destino.rsplit(".", 1)[-1] == "register_operation"


def _registradores() -> Set[str]:
    """Punto fijo: toda función del código (no tests) que llama a un registrador."""
    fuentes = []
    for f in _archivos():
        rel = f.relative_to(RAIZ).as_posix()
        if _es_test(rel):
            continue
        arbol = _parse(f)
        if arbol is not None:
            fuentes.append((_modulo(rel), arbol, _imports(arbol)))
    registradores = {SEMILLA}
    cambio = True
    while cambio:
        cambio = False
        for modulo, arbol, imports in fuentes:
            for fn in arbol.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                nombre = f"{modulo}.{fn.name}"
                if nombre in registradores:
                    continue
                if any(isinstance(c, ast.Call)
                       and _registra(_destino(c.func, imports, modulo), registradores)
                       for c in ast.walk(fn)):
                    registradores.add(nombre)
                    cambio = True
    return registradores


# ── Qué cuenta como restaurar ──────────────────────────────────────────────

def _restaura(finalbody: List[ast.stmt]) -> bool:
    for stmt in finalbody:
        for c in ast.walk(stmt):
            if not (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "update"):
                continue
            v = c.func.value
            if (isinstance(v, ast.Name) and v.id == "OPERATIONS") or (
                    isinstance(v, ast.Attribute) and v.attr == "OPERATIONS"):
                return True
    return False


def _es_fixture(fn: ast.AST) -> bool:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for d in fn.decorator_list:
        c = d.func if isinstance(d, ast.Call) else d
        if (isinstance(c, ast.Name) and c.id == "fixture") or (
                isinstance(c, ast.Attribute) and c.attr == "fixture"):
            return True
    return False


def _fixture_que_restaura(fn: ast.AST) -> bool:
    return _es_fixture(fn) and any(
        isinstance(t, ast.Try) and _restaura(t.finalbody) for t in ast.walk(fn))


def _fixtures_que_restauran(arbol: ast.AST) -> Set[str]:
    return {fn.name for fn in ast.walk(arbol)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _fixture_que_restaura(fn)}


def _pide(fn: ast.AST, fixtures: Set[str]) -> bool:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    if not isinstance(fn, ast.ClassDef):
        args = fn.args
        if {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs} & fixtures:
            return True
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "usefixtures"
                and any(isinstance(a, ast.Constant) and a.value in fixtures for a in d.args)):
            return True
    return False


def _sitios_en(fuente: str, rel: str, registradores: Set[str],
               fixtures_heredados: Set[str]) -> List[Sitio]:
    arbol = ast.parse(fuente)
    modulo = _modulo(rel)
    imports = _imports(arbol)
    fixtures = fixtures_heredados | _fixtures_que_restauran(arbol)
    sitios: List[Sitio] = []

    def visitar(nodo: ast.AST, pila: List[ast.AST]) -> None:
        if isinstance(nodo, ast.Call) and _registra(
                _destino(nodo.func, imports, modulo), registradores):
            protegido = False
            for i, ancestro in enumerate(pila):
                hijo = pila[i + 1] if i + 1 < len(pila) else nodo
                if (isinstance(ancestro, ast.Try) and hijo not in ancestro.finalbody
                        and _restaura(ancestro.finalbody)):
                    protegido = True
                elif _fixture_que_restaura(ancestro) or _pide(ancestro, fixtures):
                    protegido = True
            funciones = [a.name for a in pila
                         if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef))]
            destino = _destino(nodo.func, imports, modulo) or "?"
            sitios.append(Sitio(rel, nodo.lineno, funciones[0] if funciones else "<módulo>",
                                destino, protegido))
        for hijo in ast.iter_child_nodes(nodo):
            visitar(hijo, pila + [nodo])

    visitar(arbol, [])
    return sitios


def _fixtures_de_conftests(f: pathlib.Path) -> Set[str]:
    heredados: Set[str] = set()
    d = f.parent
    while True:
        conftest = d / "conftest.py"
        if conftest.exists():
            arbol = _parse(conftest)
            if arbol is not None:
                heredados |= _fixtures_que_restauran(arbol)
        if d == RAIZ or RAIZ not in d.parents:
            break
        d = d.parent
    return heredados


def _sitios() -> List[Sitio]:
    registradores = _registradores()
    sitios: List[Sitio] = []
    for f in _archivos():
        rel = f.relative_to(RAIZ).as_posix()
        if not _es_test(rel) or f.resolve() == pathlib.Path(__file__).resolve():
            continue
        try:
            fuente = f.read_text(encoding="utf-8")
            sitios.extend(_sitios_en(fuente, rel, registradores, _fixtures_de_conftests(f)))
        except (SyntaxError, UnicodeDecodeError):          # pragma: no cover - defensivo
            continue
    return sitios


# ── Los tests ──────────────────────────────────────────────────────────────

def test_ningun_test_registra_operaciones_sin_restaurar_el_registro():
    malos = [s for s in _sitios()
             if not s.protegido and f"{s.archivo}::{s.funcion}" not in EXCEPCIONES]
    assert not malos, "\n".join(
        f"{s.archivo}:{s.linea} · {s.funcion}() llama a {s.destino} sin restaurar "
        f"OPERATIONS. Reemplaza las Operation por otras sin los triggers que "
        f"enganchar_cascada() agregó, y rompe test_cascada.py según el orden de corrida. "
        f"Guardá dict(OPERATIONS) y restauralo en un finally, o pedí un fixture que lo haga."
        for s in malos)


def test_ninguna_EXCEPCION_esta_rancia():
    """Una excepción que ya no corresponde a una llamada desprotegida no protege nada y
    deja la puerta abierta para la próxima llamada con ese nombre."""
    desprotegidos = {f"{s.archivo}::{s.funcion}" for s in _sitios() if not s.protegido}
    rancias = sorted(set(EXCEPCIONES) - desprotegidos)
    assert not rancias, f"excepciones rancias (borralas): {rancias}"
    assert all(motivo.strip() for motivo in EXCEPCIONES.values())


def test_el_barrido_ENCUENTRA_los_casos_conocidos():
    """Un barrido que no encuentra nada sale PASSED. Los tres casos que originaron la regla
    tienen que estar entre los sitios, y los registradores de los módulos también."""
    sitios = _sitios()
    vistos = {(s.archivo, s.funcion) for s in sitios}
    assert CONOCIDOS <= vistos, f"no encontrados: {sorted(CONOCIDOS - vistos)}"
    assert len(sitios) >= 15,f"solo {len(sitios)} llamadas: ¿se rompió el barrido?"
    registradores = _registradores()
    assert "modules.sector_intel.operations.register" in registradores
    assert "modules.banking_score.alerts_producer.register" not in registradores, (
        "engancha un productor de alertas, no registra operaciones")
    assert len(registradores) >= 15


def test_el_chequeo_DETECTA_el_defecto_y_acepta_las_tres_protecciones():
    """Antes de creerle a un verde, comprobar que el instrumento ve el caso real."""
    reg = {SEMILLA, "modules.x.operations.register"}
    cabecera = (
        "import pytest\n"
        "import modules.x.operations as ops\n"
        "from shared.operations.service import OPERATIONS\n")
    fixture = (
        "@pytest.fixture()\n"
        "def temp_ops():\n"
        "    saved = dict(OPERATIONS)\n"
        "    try:\n"
        "        yield\n"
        "    finally:\n"
        "        OPERATIONS.clear()\n"
        "        OPERATIONS.update(saved)\n")

    def protegidos(cuerpo: str, heredados: Iterable[str] = ()) -> List[bool]:
        return [s.protegido for s in _sitios_en(cabecera + cuerpo, "m/tests/test_x.py",
                                                reg, set(heredados))]

    assert protegidos("def test_a():\n    ops.register()\n") == [False]
    assert protegidos(
        "def test_a():\n"
        "    saved = dict(OPERATIONS)\n"
        "    try:\n"
        "        ops.register()\n"
        "    finally:\n"
        "        OPERATIONS.update(saved)\n") == [True]
    # Un finally que no restaura no protege.
    assert protegidos(
        "def test_a():\n"
        "    try:\n"
        "        ops.register()\n"
        "    finally:\n"
        "        pass\n") == [False]
    assert protegidos(fixture + "def test_a(temp_ops):\n    ops.register()\n") == [True]
    assert protegidos(fixture + "@pytest.mark.usefixtures('temp_ops')\n"
                                "def test_a():\n    ops.register()\n") == [True]
    assert protegidos("def test_a(temp_ops):\n    ops.register()\n", {"temp_ops"}) == [True]
    # Pedir un fixture que NO restaura no protege.
    assert protegidos("def test_a(db):\n    ops.register()\n") == [False]
    # El nombre `register` no basta: otro módulo no registra operaciones.
    assert protegidos("import modules.y.alerts as ap\ndef test_a():\n    ap.register()\n") == []
