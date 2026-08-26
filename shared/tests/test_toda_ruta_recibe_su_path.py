"""Toda ruta declara parámetros que su función RECIBE.

**El defecto que lo obligó.** En `law_intel/api/router.py` alguien insertó un helper de dos
líneas entre el decorador y la función que ese decorador anotaba:

    @router.get("/{expediente_id}/informe-abierto", ...)
    def _hoy() -> str:                       # ← el decorador aterrizó acá
        return datetime.date.today().isoformat()

    def informe_abierto_(expediente_id, fmt, db, ...):   # ← nunca se registró

La ruta quedó servida por `_hoy`. `GET /api/v1/law-intel/ley_167_21/informe-abierto`
devolvía `"2026-08-26"` con HTTP 200 — no un error, una fecha. El tercer entregable del
producto de leyes, el único que se comparte con externos, **no se podía descargar de la
plataforma durante un día** mientras los tests seguían verdes: probaban `render()`, que
funcionaba perfecto, por debajo de la ruta.

**Por qué este chequeo y no otro.** FastAPI no se queja: un `{expediente_id}` en el path
sin argumento correspondiente en la firma es legal para el framework, que simplemente lo
ignora. Y un handler que devuelve 200 no dispara ninguna alarma. Lo único que delata el
error sin ambigüedad es la relación entre el path y la firma — que es exactamente la que se
rompe cuando un decorador aterriza en la función equivocada.

Se lee el código con `ast` y no se importan los routers: la regla tiene que valer también
para un módulo que no arranque en el entorno de test.
"""
import ast
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[2]
VERBOS = ("get", "post", "put", "delete", "patch")
#: Los objetos sobre los que se declara una ruta. `app` incluido: `main.py` declara algunas.
PORTADORES = ("router", "app")

#: Lo que no se lee. Los worktrees son copias de trabajo de otras sesiones —con el código
#: viejo dentro— y un test que las lea falla por un defecto que ya se arregló acá.
EXCLUIDOS = (".venv", "/tests/", ".claude/worktrees", "node_modules", "/.git/")


def _rutas():
    """`(archivo, línea, nombre, path, argumentos)` de cada ruta declarada en el repo."""
    for f in RAIZ.rglob("*.py"):
        if any(x in str(f) for x in EXCLUIDOS):
            continue
        try:
            arbol = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):          # pragma: no cover - defensivo
            continue
        for n in ast.walk(arbol):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                c = d.func if isinstance(d, ast.Call) else d
                if not (isinstance(c, ast.Attribute) and c.attr in VERBOS):
                    continue
                if not (isinstance(c.value, ast.Name) and c.value.id in PORTADORES):
                    continue
                if not (isinstance(d, ast.Call) and d.args
                        and isinstance(d.args[0], ast.Constant)):
                    continue
                args = {a.arg for a in n.args.args + n.args.kwonlyargs}
                yield (f.relative_to(RAIZ), n.lineno, n.name, str(d.args[0].value), args)


def test_ninguna_ruta_pierde_un_parametro_de_su_path():
    malas = []
    for archivo, linea, nombre, path, args in _rutas():
        faltan = set(re.findall(r"\{([a-zA-Z_][a-zA-Z_0-9]*)", path)) - args
        if faltan:
            malas.append(
                f"{archivo}:{linea} · «{path}» → {nombre}() no recibe {sorted(faltan)}. "
                f"Si el decorador aterrizó en la función equivocada, la ruta responde 200 "
                f"con lo que devuelva esa otra función y nadie se entera.")
    assert not malas, "\n".join(malas)


def test_el_barrido_ENCUENTRA_rutas():
    """Un `@parametrize` vacío sale SKIPPED y un barrido que no encuentra nada sale PASSED.

    Si el glob deja de encontrar los routers —una mudanza de carpeta, un `rglob` mal
    escrito—, el test de arriba pasa sin haber mirado una sola ruta.
    """
    assert len(list(_rutas())) > 300


def test_el_chequeo_DETECTA_el_defecto_que_lo_originó():
    """Antes de creerle a un verde, comprobar que el instrumento ve el caso real."""
    fuente = (
        "@router.get('/{expediente_id}/informe-abierto')\n"
        "def _hoy() -> str:\n"
        "    return '2026-08-26'\n")
    arbol = ast.parse(fuente)
    fn = arbol.body[0]
    args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    faltan = set(re.findall(r"\{([a-zA-Z_][a-zA-Z_0-9]*)",
                            fn.decorator_list[0].args[0].value)) - args
    assert faltan == {"expediente_id"}
