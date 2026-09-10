"""REGLA ESTRUCTURAL: en observabilidad hay UN SOLO reloj, y es UTC.

**El defecto.** ``test_el_rango_incluye_el_DIA_COMPLETO_de_hasta`` sembraba una corrida con
«ahora» —sellada en UTC por la base— y preguntaba por un rango que terminaba en
``date.today()``, el reloj LOCAL. Pasadas las 20:00 AST el día UTC ya es el siguiente, la
corrida cae fuera del rango y el test se pone rojo por la hora a la que se lo corre. El rojo
no era del código bajo prueba, y comerse un rojo ajeno cada noche enseña a ignorarlos.

**Por qué esto tiene que leer el CÓDIGO y no puede ser un test de comportamiento.** Se
comprobó: mutando el motor para que el rango por defecto use ``date.today()``, la suite de
comportamiento sale ROJA en ``America/Santo_Domingo`` y VERDE en ``UTC`` y ``Asia/Tokyo``.
CI corre en UTC. Es decir: una deriva de reloj en el motor es INDETECTABLE en CI por
construcción, se escriba como se escriba el test. El único instrumento que la ve es este.

**Qué gobierna.** Las filas de estos paneles las sella la base (``server_default=func.now()``,
UTC) y los cuatro motores arman su rango con ``datetime.now(timezone.utc)``; el frontend manda
las fechas con ``toISOString()``, que también es UTC. Un reloj local en este paquete es un
TERCER reloj, y su síntoma —unas corridas de menos en el borde del día— se lee como «se usó
menos», que es una conclusión comercial equivocada e indistinguible de la verdadera.

Si algún día hace falta el reloj local acá, se declara en la línea con ``# reloj-local: <motivo>``.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple, TypeGuard

#: Raíz del paquete. Se barre COMPLETO —motor y tests—: el defecto vivió en un test, y un
#: glob que dejara `tests/` afuera habría pasado por encima del caso real.
_PAQUETE = Path(__file__).resolve().parents[1]

#: Los cuatro paneles que filtran por rango de fechas. Van nombrados para que el barrido no
#: pueda quedarse vacío ni encogerse en silencio si alguien mueve un archivo.
_PANELES = ("spend.py", "marcas_del_guard.py", "tiempos_de_narrativa.py",
            "uso_de_herramientas.py")

#: Marca de excepción declarada, en la misma línea de la llamada.
_EXCEPCION = "# reloj-local:"


def _fuentes() -> List[Path]:
    return sorted(p for p in _PAQUETE.rglob("*.py") if p.name != "__init__.py")


def _es_reloj_local(nodo: ast.AST) -> TypeGuard[ast.Call]:
    """``date.today()`` / ``datetime.today()`` / ``datetime.now()`` sin zona.

    ``datetime.now(timezone.utc)`` NO cuenta: lleva su zona explícita, que es justo lo que se
    exige. Se lee con ``ast`` y no con una expresión regular porque un paréntesis dentro de un
    comentario ya truncó la lista de un guard en este repo y lo dejó ciego sin avisar.

    Devuelve ``TypeGuard`` y no ``bool`` para que quien recorre con ``ast.walk`` —que entrega
    ``ast.AST``, sin ``lineno``— pueda leer la línea del hallazgo sin un cast a ciegas.
    """
    if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
        return False
    base = nodo.func.value
    if not isinstance(base, ast.Name) or base.id not in {"date", "datetime"}:
        return False
    if nodo.func.attr == "today":
        return True
    # `.now()` sin argumento, o con `None` explícito, devuelve hora LOCAL ingenua.
    if nodo.func.attr == "now":
        if not nodo.args and not nodo.keywords:
            return True
        primero = nodo.args[0] if nodo.args else None
        return isinstance(primero, ast.Constant) and primero.value is None
    return False


def _infracciones(ruta: Path) -> List[Tuple[int, str]]:
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    arbol = ast.parse("\n".join(lineas), filename=str(ruta))
    halladas: List[Tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if not _es_reloj_local(nodo):
            continue
        linea = lineas[nodo.lineno - 1]
        if _EXCEPCION in linea:
            continue
        halladas.append((nodo.lineno, linea.strip()))
    return halladas


# ── El barrido encontró algo (si no, este archivo entero es decorativo) ──────────

def test_el_barrido_ve_los_CUATRO_paneles():
    """Un barrido vacío sale en verde y no protege de nada. Acá se le exige piso y nombres:
    si alguien mueve o renombra un panel, esto falla en vez de encogerse callado."""
    vistos = {p.name for p in _fuentes()}
    assert len(vistos) >= 10, f"el barrido encogió: solo {len(vistos)} archivos"
    faltan = set(_PANELES) - vistos
    assert not faltan, f"el barrido dejó paneles afuera: {faltan}"
    assert any(p.parent.name == "tests" for p in _fuentes()), (
        "el barrido no está entrando en tests/, que es donde vivió el defecto")


# ── El detector tiene dientes (si no, el barrido es un adorno) ───────────────────

def _detecta(fuente: str) -> bool:
    return any(_es_reloj_local(n) for n in ast.walk(ast.parse(fuente)))


def test_el_detector_CAZA_el_reloj_local():
    """El propio guard, contra el código exacto que produjo el rojo."""
    assert _detecta("hoy = date.today()")
    assert _detecta("hoy = datetime.today()")
    assert _detecta("ahora = datetime.now()")
    assert _detecta("ahora = datetime.now(None)")
    assert _detecta("r = resumen(db, hasta=date.today())")


def test_el_detector_NO_marca_el_reloj_correcto():
    """Un guard que marca todo se desactiva a la semana."""
    assert not _detecta("ahora = datetime.now(timezone.utc)")
    assert not _detecta("hoy = datetime.now(timezone.utc).date()")
    assert not _detecta("fin = hasta or datetime.now(tz=timezone.utc).date()")
    assert not _detecta("t0 = time.perf_counter()")
    assert not _detecta("d = date(2026, 5, 14)")


# ── La regla ────────────────────────────────────────────────────────────────────

def test_observabilidad_no_lee_NUNCA_el_reloj_local():
    culpables = {
        str(ruta.relative_to(_PAQUETE)): hallazgos
        for ruta in _fuentes()
        if (hallazgos := _infracciones(ruta))
    }
    assert not culpables, (
        "reloj LOCAL en observabilidad — las filas se sellan en UTC y los rangos se arman en "
        "UTC; un tercer reloj pierde las corridas del borde del día y el panel subcuenta sin "
        "que falle nada:\n" + "\n".join(
            f"  {archivo}:{n}  {linea}"
            for archivo, hallazgos in sorted(culpables.items())
            for n, linea in hallazgos))
