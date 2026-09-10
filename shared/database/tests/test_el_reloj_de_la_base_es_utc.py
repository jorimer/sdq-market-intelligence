"""El reloj de la base es UTC en TODA conexión, no por lo que diga el servidor.

``created_at``/``updated_at`` los escribe PostgreSQL con ``now()`` en columnas sin zona, y eso
se convierte al ``TimeZone`` de la SESIÓN. Los rangos de fechas se arman en UTC desde Python.
Si el servidor no está en UTC, cada fila queda corrida contra el rango que la busca y se
pierden las del borde del día, con un conteo apenas más bajo como único síntoma.

**Por qué ningún test de comportamiento puede ver esto.** La batería corre sobre SQLite, cuyo
``CURRENT_TIMESTAMP`` siempre es UTC, y CI no tiene Postgres. Por eso acá se prueba la
CONEXIÓN que abre el engine real —qué parámetros le llegan a psycopg2— y se lee el código
para exigir que todo engine pase por el mismo lugar.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import textwrap
from typing import List, Tuple, TypeGuard

from shared.database.conexion import OPCION_RELOJ_UTC, connect_args_para

RAIZ = pathlib.Path(__file__).resolve().parents[3]

#: Donde vive código que construye engines. `frontend/` no tiene Python; `tests/` se excluye
#: porque sus engines son SQLite en memoria y no escriben en la base de nadie.
_DIRECTORIOS = ("shared", "modules", "app", "infrastructure", "scripts")

_CONSTRUCTORES = {"create_engine", "create_async_engine", "engine_from_config"}

#: Excepción declarada, en la línea de la llamada.
_EXCEPCION = "# reloj-de-la-base:"


# ── Los argumentos ───────────────────────────────────────────────────────────────

def test_postgres_arranca_cada_conexion_en_UTC():
    for url in ("postgresql://u:p@h:5432/db", "postgresql+psycopg2://u:p@h/db"):
        assert connect_args_para(url) == {"options": OPCION_RELOJ_UTC}, url


def test_las_options_que_ya_traia_la_URL_se_CONSERVAN():
    """`connect_args` pisa la query de la URL: devolver solo la nuestra borraría las del
    operador sin aviso."""
    url = "postgresql://u:p@h/db?options=-c%20statement_timeout%3D5000"
    opciones = connect_args_para(url)["options"]
    assert "statement_timeout=5000" in opciones
    assert OPCION_RELOJ_UTC in opciones


def test_sqlite_no_recibe_parametros_de_postgres():
    assert connect_args_para("sqlite:///./data/x.db") == {"check_same_thread": False}
    assert connect_args_para("sqlite://") == {"check_same_thread": False}


# ── El engine REAL de la aplicación ──────────────────────────────────────────────

_SONDA = textwrap.dedent("""
    import json, psycopg2
    capturado = {}

    class _NoConectar(Exception):
        pass

    def _connect(*args, **kwargs):
        capturado.update(kwargs)
        raise _NoConectar()

    psycopg2.connect = _connect
    from shared.database.session import engine
    try:
        engine.connect()
    except Exception:
        pass
    print("SONDA=" + json.dumps({"options": capturado.get("options"),
                                 "llego_a_conectar": bool(capturado)}))
""")


def test_el_engine_de_la_APLICACION_conecta_con_el_reloj_en_UTC():
    """Se importa `shared.database.session` con una URL de Postgres, en un proceso aparte, y se
    mira qué recibe `psycopg2.connect`. Nunca llega a la red: la conexión se corta ahí.

    Es la prueba sobre la RUTA y no sobre el motor: `connect_args_para` puede estar perfecta
    y el engine de la aplicación no usarla.
    """
    entorno = dict(os.environ,
                   DATABASE_URL="postgresql+psycopg2://sonda:sonda@127.0.0.1:1/sonda")
    salida = subprocess.run([sys.executable, "-c", _SONDA], cwd=RAIZ, env=entorno,
                            capture_output=True, text=True, timeout=120)
    lineas = [ln for ln in salida.stdout.splitlines() if ln.startswith("SONDA=")]
    assert lineas, f"la sonda no reportó nada:\n{salida.stdout}\n{salida.stderr}"
    sonda = json.loads(lineas[-1].removeprefix("SONDA="))
    assert sonda["llego_a_conectar"], "el engine nunca intentó conectar: la sonda no midió nada"
    assert sonda["options"] and OPCION_RELOJ_UTC in sonda["options"], (
        f"la conexión de la aplicación arranca sin fijar su reloj: options={sonda['options']!r}")


# ── Todo engine pasa por el mismo lugar ──────────────────────────────────────────

def _fuentes() -> List[pathlib.Path]:
    return sorted(
        p for d in _DIRECTORIOS for p in (RAIZ / d).rglob("*.py")
        if "tests" not in p.relative_to(RAIZ).parts and not p.name.startswith("test_"))


def _nombre(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _construye_engine(nodo: ast.AST) -> TypeGuard[ast.Call]:
    return isinstance(nodo, ast.Call) and _nombre(nodo.func) in _CONSTRUCTORES


def _usa_el_reloj(llamada: ast.Call) -> bool:
    return any(
        kw.arg == "connect_args" and isinstance(kw.value, ast.Call)
        and _nombre(kw.value.func) == "connect_args_para"
        for kw in llamada.keywords)


def _sitios(fuente: str) -> List[Tuple[int, bool]]:
    """(línea, usa el reloj) de cada engine construido en `fuente`."""
    return [(n.lineno, _usa_el_reloj(n)) for n in ast.walk(ast.parse(fuente))
            if _construye_engine(n)]


def test_el_barrido_ENCUENTRA_los_engines_conocidos():
    """Un barrido vacío pasa en verde. Se le exige ver los dos que no pueden faltar."""
    con_engine = {str(p.relative_to(RAIZ)) for p in _fuentes()
                  if _sitios(p.read_text(encoding="utf-8"))}
    for esperado in ("shared/database/session.py", "infrastructure/alembic/env.py"):
        assert esperado in con_engine, f"el barrido no ve {esperado}: {sorted(con_engine)}"


def test_el_detector_distingue_un_engine_con_y_sin_reloj():
    assert _sitios("e = create_engine(url)") == [(1, False)]
    assert _sitios("e = create_engine(url, connect_args={})") == [(1, False)]
    assert _sitios("e = sqlalchemy.create_engine(url, connect_args=connect_args_para(url))") \
        == [(1, True)]
    assert _sitios("c = engine_from_config(cfg, prefix='x.')") == [(1, False)]
    assert _sitios("x = crear(url)") == []


def test_todo_engine_de_la_plataforma_fija_el_reloj_de_la_base():
    culpables = []
    for ruta in _fuentes():
        lineas = ruta.read_text(encoding="utf-8").splitlines()
        for n, usa in _sitios("\n".join(lineas)):
            if not usa and _EXCEPCION not in lineas[n - 1]:
                culpables.append(f"  {ruta.relative_to(RAIZ)}:{n}  {lineas[n - 1].strip()}")
    assert not culpables, (
        "engine construido sin `connect_args=connect_args_para(url)`: sus conexiones escriben "
        "`created_at` con el huso del servidor y no con UTC.\n" + "\n".join(culpables))
