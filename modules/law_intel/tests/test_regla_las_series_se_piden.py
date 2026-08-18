"""REGLA ESTRUCTURAL: quien evalúa un indicador contra su meta PIDE las series.

**El caso, que costó dos veces.** ``panel()`` recibe las observaciones en un diccionario.
La ruta ``/semaforo`` lo llamaba con ``{}`` literal. Mientras hubo cero bindings verificados
eso fue indistinguible de lo correcto: todo respondía ``sin_medicion``, que era la verdad.

Al llegar el primer binding verificado la mentira se volvió visible, y en la peor forma
posible: el semáforo —el veredicto por indicador, el corazón del informe— decía «el binding
está verificado y la serie no devolvió valor» en los TRECE, mientras la cobertura de su
propia portada decía «mide 13 de 90». El documento se contradecía consigo mismo.

**Por qué un test estructural y no una lección.** La lección ya estaba escrita, y en el
propio repo: ``products.py`` arregló exactamente esto en el camino de informes y dejó el
comentario «Sin esto el informe diría "mide 4 de 90" y después "sin dato" en los cuatro».
La ruta de API quedó con el dict vacío igual. Un motor que recibe su entrada vacía no falla:
DESAPARECE, y responde con la forma correcta y el contenido de un producto sin datos.

**Qué exige.** Que el argumento de series de estas funciones no sea un literal vacío. No
exige una fuente concreta —un test puede armar sus observaciones a mano, y de hecho debe—;
exige que en el código de producción nadie evalúe contra un diccionario que sabe vacío.
"""
import ast
import pathlib

import pytest

MODULO = pathlib.Path(__file__).resolve().parent.parent

#: Funciones que evalúan indicadores contra sus metas. La posición es la del argumento que
#: lleva las observaciones; ``None`` cuando solo viaja por palabra clave.
_EVALUADORES = {"panel": 2, "law_ai_context": 2, "series_de": None}

#: Los tests SÍ pueden pasar diccionarios vacíos —probar el caso «sin dato» es legítimo y
#: necesario—. La regla protege el código que corre en producción.
_EXENTOS = {"tests"}


def _archivos_de_produccion():
    for path in sorted(MODULO.rglob("*.py")):
        if _EXENTOS & set(path.parts):
            continue
        yield path


def _vacio(nodo) -> bool:
    """Un literal que el autor escribió sabiendo que está vacío: ``{}``, ``dict()``, ``()``."""
    if isinstance(nodo, ast.Dict) and not nodo.keys:
        return True
    if isinstance(nodo, (ast.Tuple, ast.List)) and not nodo.elts:
        return True
    return (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "dict" and not nodo.args and not nodo.keywords)


def _infracciones():
    for path in _archivos_de_produccion():
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(arbol):
            if not isinstance(n, ast.Call):
                continue
            nombre = (n.func.id if isinstance(n.func, ast.Name)
                      else n.func.attr if isinstance(n.func, ast.Attribute) else None)
            if nombre not in _EVALUADORES:
                continue
            pos = _EVALUADORES[nombre]
            candidatos = [k.value for k in n.keywords if k.arg in ("series", "proveedor")]
            if pos is not None and len(n.args) > pos:
                candidatos.append(n.args[pos])
            for c in candidatos:
                if _vacio(c):
                    yield f"{path.relative_to(MODULO.parent.parent)}:{n.lineno} → {nombre}()"


def test_ningun_evaluador_de_produccion_recibe_las_series_vacias():
    malas = list(_infracciones())
    assert not malas, (
        "Se evalúa contra un diccionario de series vacío en:\n  " + "\n  ".join(malas)
        + "\nEso no falla: responde `sin_dato` en indicadores que SÍ están medidos, y "
          "contradice a la cobertura del mismo informe. Pedí las series al proveedor.")


def test_la_regla_tiene_dientes():
    """Antes de confiar en un test estructural hay que verlo rechazar el código VIEJO."""
    viejo = ast.parse("veredictos = panel(e.numerados, bs, {}, corte)")
    llamada = next(n for n in ast.walk(viejo) if isinstance(n, ast.Call))
    assert _vacio(llamada.args[2]), "la forma exacta que se publicó tiene que dar positivo"


@pytest.mark.parametrize("fuente", [
    "panel(a, b, series_de(bs, proveedor_registro(db)), corte)",
    "panel(a, b, series, corte)",
    "law_ai_context(eid, corte, series)",
])
def test_la_regla_no_muerde_lo_correcto(fuente):
    llamada = next(n for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.Call))
    assert not _vacio(llamada.args[2])
