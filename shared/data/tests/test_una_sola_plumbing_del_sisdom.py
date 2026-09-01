"""UNA sola plumbing del SISDOM. Leído del código con `ast`, no confiado a un comentario.

**Qué pasó.** `shared/data/sisdom_common.py` nació justamente para que no hubiera dos copias
del descubrimiento, y lo dejó escrito en su docstring: *"que no haya dos copias que envejezcan
por separado — que es exactamente cómo se rompe un conector cuando el emisor cambia algo y solo
se arregla una de las dos"*. Aun así `sisdom_income.py` conservó la suya, con su propio
``LISTING_URL``, su propio ``discover_book`` y su propia ``SisdomUnavailable``.

El 2026-09-01 el MEPyD desapareció y se cumplió la profecía al pie de la letra: el libro de la
END ya se había recableado a Hacienda —hardcodeando la URL— y las otras cuatro series
(ingreso, escolaridad, mortalidad infantil, pobreza por zona) se quedaron apuntando a un host
que devuelve 301 a un 404.

**La lección escrita ya falló una vez, así que ahora es un test.** La doctrina del repo es
explícita: cuando un defecto se repite, la cura es un test estructural que lee el código, no
una advertencia más en un docstring.

Se lee con `ast` y no con `grep`: un paréntesis dentro de un comentario ya truncó la lista de
otro guard en este mismo repo y sacó tres archivos de la regla sin que nada avisara.
"""
import ast
from pathlib import Path

import pytest

_DATA = Path(__file__).resolve().parents[1]
_COMUN = "sisdom_common.py"

#: Los módulos del SISDOM que NO son la plumbing. Se descubren del directorio —no se
#: enumeran— para que un conector nuevo entre a la regla solo. Si se enumeraran, el que se
#: agregue mañana quedaría afuera, que es la forma en que estas reglas se vacían.
MODULOS = sorted(p for p in _DATA.glob("sisdom_*.py") if p.name != _COMUN)

#: Marcas de que un módulo se armó SU PROPIA plumbing en vez de usar la común.
HOSTS_PROHIBIDOS = ("mepyd.gob.do", "hacienda.gob.do", "admin-ajax.php")


def test_el_barrido_encuentra_modulos():
    """Un barrido que no encuentra nada pasa en verde sin proteger nada."""
    assert len(MODULOS) >= 4, [p.name for p in MODULOS]


def _docstrings(arbol: ast.AST) -> set:
    """Los nodos que son DOCUMENTACIÓN, para no prohibir la explicación junto con el defecto.

    La historia de esta rotura se cuenta nombrando los hosts —hay que poder escribir «mepyd
    dejó de existir»—. Prohibir la palabra en la prosa empujaría a borrar el porqué, que es
    justo lo que hace que el próximo la repita."""
    docs = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        primero = nodo.body[0] if nodo.body else None
        if isinstance(primero, ast.Expr) and isinstance(primero.value, ast.Constant):
            docs.add(id(primero.value))
    return docs


@pytest.mark.parametrize("ruta", MODULOS, ids=lambda p: p.name)
def test_ningun_conector_clava_el_host_del_emisor(ruta: Path):
    """La URL del emisor vive en UN lugar. Clavarla acá es lo que hay que arreglar N veces
    el día que el emisor se mude — y lo que hizo que se arreglara una sola."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    docs = _docstrings(arbol)
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                and id(nodo) not in docs):
            for host in HOSTS_PROHIBIDOS:
                assert host not in nodo.value, (
                    f"{ruta.name} clava «{host}» en un literal. El descubrimiento y la "
                    f"descarga viven en {_COMUN}: usá `fetch_book`/`fetch_book_con_edicion`.")


@pytest.mark.parametrize("ruta", MODULOS, ids=lambda p: p.name)
def test_ningun_conector_reimplementa_el_descubrimiento(ruta: Path):
    """Nadie define su propio `discover_*` ni su propia `SisdomUnavailable`: dos versiones de
    la misma regla es cómo una gana un guard y la otra no."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not nodo.name.startswith("discover"), (
                f"{ruta.name} define `{nodo.name}`: el descubrimiento vive en {_COMUN}.")
        if isinstance(nodo, ast.ClassDef):
            assert nodo.name != "SisdomUnavailable", (
                f"{ruta.name} redefine `SisdomUnavailable`: se importa de {_COMUN}, o un "
                "`except` de quien llama deja de atrapar la mitad de los fallos.")


@pytest.mark.parametrize("ruta", MODULOS, ids=lambda p: p.name)
def test_todo_conector_baja_por_la_plumbing_comun(ruta: Path):
    """Todo módulo que hable con la red lo hace por `fetch_book*`. Se detecta por el uso de
    un cliente HTTP: un módulo que importa `httpx` se armó su propia descarga."""
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importa_http = any(
        (isinstance(n, ast.Import) and any(a.name.split(".")[0] in {"httpx", "requests"}
                                           for a in n.names))
        or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0]
            in {"httpx", "requests"})
        for n in ast.walk(arbol))
    assert not importa_http, (
        f"{ruta.name} abre su propio cliente HTTP. La descarga vive en {_COMUN} para que un "
        "cambio del emisor se arregle UNA vez.")
