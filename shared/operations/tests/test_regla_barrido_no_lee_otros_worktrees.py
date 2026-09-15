"""Todo barrido que arranca en la RAÍZ del repo excluye ``.claude``.

**Por qué existe este archivo.** Las sesiones concurrentes dejan worktrees —árboles
COMPLETOS de otras ramas— bajo ``.claude/worktrees/``. Un glob enraizado en el repo los
lee como si fueran código de esta rama. Medido el 2026-08-24 sobre el checkout principal
con 10 worktrees: ``test_firma_de_los_runners`` evaluaba 840 runners en vez de 80. Las
consecuencias no son cosméticas: un archivo mal escrito en la rama de OTRO hace fallar tu
suite, la corrida se vuelve diez veces más lenta, y toda cota inferior del tipo "esperaba
~78" deja de proteger porque la inflación la supera sola. CI no lo ve —clona limpio, sin
worktrees—, así que el defecto vive entero en el desarrollo local.

**Por qué un test y no una lección.** Ya pasó dos veces. ``test_regla_toda_llamada_se_
contabiliza`` tuvo la exclusión, una reescritura se la llevó por delante, y volvió con un
test propio que la vigila; ``test_firma_de_los_runners`` nunca la tuvo. Es exactamente el
patrón "el guard existe en un motor y falta en el gemelo", que en este repo la lección
escrita no curó ninguna de las siete veces. Lo que cura es leer el código.

**Qué cuenta como barrido desde la raíz.** ``RAIZ.rglob("*.py")`` y ``RAIZ.glob("**/*.py")``
sí: el patrón arranca con comodín, así que el barrido puede caer en cualquier subdirectorio.
``RAIZ.glob("modules/*/ai_context.py")`` no: el primer segmento fija la rama del árbol y
``.claude`` queda fuera solo. ``(RAIZ / paquete).rglob(...)`` tampoco, por lo mismo.
"""
import ast
import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
_EXCLUIDOS = {".venv", "node_modules", ".git", "__pycache__", "frontend", ".claude"}
_PAQUETES = ("shared", "modules", "app", "infrastructure", "scripts")


def _fuentes():
    for paquete in _PAQUETES:
        base = _RAIZ / paquete
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(_RAIZ)
            if _EXCLUIDOS & set(rel.parts):
                continue
            yield rel, p


def _variables_raiz(arbol: ast.AST, rel: pathlib.Path) -> set[str]:
    """Nombres asignados a ``pathlib.Path(__file__)...parents[N]`` con N = la raíz del repo.

    ``shared/operations/tests/x.py`` tiene 4 partes: ``parents[3]`` es la raíz. Cualquier
    otro N apunta a un subárbol y no nos interesa.
    """
    profundidad_raiz = len(rel.parts) - 1
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Subscript):
            continue
        sub = nodo.value
        if getattr(sub.value, "attr", None) != "parents":
            continue
        if not (isinstance(sub.slice, ast.Constant) and sub.slice.value == profundidad_raiz):
            continue
        if "__file__" not in ast.dump(sub.value):
            continue
        nombres.update(d.id for d in nodo.targets if isinstance(d, ast.Name))
    return nombres


def _barridos_desde_la_raiz(arbol: ast.AST, raices: set[str]) -> list[tuple[int, str]]:
    """``(línea, patrón)`` de cada ``RAIZ.glob/rglob`` cuyo patrón arranca con comodín."""
    hallados: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)):
            continue
        if nodo.func.attr not in ("glob", "rglob"):
            continue
        # El receptor tiene que ser el NOMBRE de la raíz pelado. `(RAIZ / x).rglob(...)`
        # es un BinOp y ya está acotado a una rama del árbol.
        if not (isinstance(nodo.func.value, ast.Name) and nodo.func.value.id in raices):
            continue
        arg = nodo.args[0] if nodo.args else None
        patron = str(arg.value) if isinstance(arg, ast.Constant) else "?"
        primer_segmento = patron.replace("\\", "/").split("/")[0]
        if "*" in primer_segmento or patron == "?":
            hallados.append((nodo.lineno, patron))
    return hallados


def _infractores() -> tuple[list, list]:
    """``(rel, línea, patrón)`` de todo barrido desde la raíz que no declare ``.claude``."""
    total: list[tuple[pathlib.Path, int, str]] = []
    malos: list[tuple[pathlib.Path, int, str]] = []
    for rel, p in _fuentes():
        texto = p.read_text(encoding="utf-8")
        try:
            arbol = ast.parse(texto)
        except SyntaxError:
            continue
        raices = _variables_raiz(arbol, rel)
        if not raices:
            continue
        for linea, patron in _barridos_desde_la_raiz(arbol, raices):
            total.append((rel, linea, patron))
            if ".claude" not in texto:
                malos.append((rel, linea, patron))
    return total, malos


def test_el_barrido_encuentra_barridos():
    """Un detector que no detecta nada pasa en verde sin proteger: si el patrón deja de
    reconocer los globs enraizados, este test lo dice en vez de dar un falso verde."""
    total, _ = _infractores()
    assert len(total) >= 3, (
        f"el detector encontró {len(total)} barridos desde la raíz; esperaba al menos 3 "
        f"(firma de runners, directorio sqlite, toda llamada se contabiliza): {total}")


def test_todo_barrido_desde_la_raiz_excluye_los_worktrees():
    _, malos = _infractores()
    assert not malos, "\n".join(
        f"{rel}:{linea} — barre la raíz con {patron!r} y no excluye `.claude`: lee los "
        f"worktrees de las otras sesiones como si fueran código de esta rama."
        for rel, linea, patron in malos)
