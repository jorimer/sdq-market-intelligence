"""REGLA ESTRUCTURAL: en el contexto de IA, el sujeto viaja con el número.

**El caso que la motivó.** `insurance_intel/ai_context.py` pasaba al modelo una clave
`concentracion_top4_pct` cuyo valor era la suma de los cuatro RAMOS de mayor peso. La tabla
del PDF lo rotulaba bien —«Concentración top-4 ramos»— pero la clave que veía el modelo había
perdido el sujeto, y justo debajo venía `aseguradoras_activas: 26`. El Deep Dive salió
afirmando que «cuatro compañías concentran el 87,1% de las primas». El número era correcto:
lo que se perdió camino al modelo fue de qué era. La cifra real por compañía es ~69%.

**Por qué un test y no una lección.** Este repo ya acumuló seis instancias de un guard
presente en un motor y ausente en otro, y la lección escrita no alcanzó ninguna de las veces.
Lo que sí funcionó fue leer el código con `ast` y exigir la regla.

**La regla.** Toda clave de un dict de contexto que represente una CUOTA, PARTICIPACIÓN o
CONCENTRACIÓN tiene que nombrar sobre qué población se computa. `top4_ramos_pct` sí;
`top4_pct` no. Si el sujeto es evidente por el prefijo (`hhi_exports`, `broadband_share`,
`sqm_share_pct` dentro de una fila ya rotulada), se declara con `# sujeto-ok: <razón>`.
"""
import ast
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

# El vocabulario NO vive acá. La misma regla la aplica el gate de alertas
# (`shared/alerts/gate.py`), y dos copias divergen: se lee de `shared.narrative.sujeto`.
from shared.narrative.sujeto import EXENCION as _EXENCION  # noqa: E402
from shared.narrative.sujeto import PORCION as _PORCION  # noqa: E402
from shared.narrative.sujeto import SUJETOS as _SUJETOS  # noqa: E402


def _exento(lineas, lineno: int) -> bool:
    """¿Hay `# sujeto-ok:` en esa línea o en el bloque de comentario contiguo de arriba?"""
    i = lineno - 1
    if i >= len(lineas):
        return False
    if _EXENCION in lineas[i]:
        return True
    j = i - 1
    while j >= 0 and lineas[j].strip().startswith("#"):
        if _EXENCION in lineas[j]:
            return True
        j -= 1
    return False


def _contextos():
    """Todo archivo que arme contexto para el modelo.

    No alcanza con `modules/*/ai_context.py`: banca —el módulo más grande— no tiene ese
    archivo y arma su contexto en `reports/narrative.py` y `products.py`, así que quedaba
    entero fuera de la regla. Cada módulo declara sus fuentes con `AI_CONTEXT_FILES` en
    `products.py`; el glob es el caso por defecto.
    """
    rutas = set(RAIZ.glob("modules/*/ai_context.py"))
    # La declaración se busca en CUALQUIER archivo del módulo, no solo en `products.py`: banca
    # la mudó a `ai_context_files.py` porque la comparten sus DOS productos, y este lector
    # —anclado al nombre del archivo— dejó de encontrarla y sacó a banca entera de la regla
    # sin que nada fallara por el motivo real. Se ancla al SÍMBOLO, que es lo que importa.
    for carpeta in sorted(RAIZ.glob("modules/*/")):
        for fuente in sorted(carpeta.glob("*.py")):
            m = re.search(r"^AI_CONTEXT_FILES\s*=\s*\(([^)]*)\)",
                          fuente.read_text(encoding="utf-8"), re.M | re.S)
            if not m:
                continue
            for rel in re.findall(r'"([^"]+)"', m.group(1)):
                ruta = carpeta / rel
                if ruta.exists():
                    rutas.add(ruta)
    return sorted(rutas)


def test_hay_contextos_que_revisar():
    """Si el glob deja de encontrar archivos, el test pasaría vacío y no protegería nada."""
    assert len(_contextos()) >= 10


def test_banca_esta_cubierta():
    """El módulo más grande no tiene `ai_context.py`; sin la declaración quedaba fuera."""
    nombres = {p.name for p in _contextos()}
    rutas = {str(p.relative_to(RAIZ)) for p in _contextos()}
    assert "modules/banking_score/reports/narrative.py" in rutas, (
        "banca declara AI_CONTEXT_FILES pero la regla no lo está leyendo")
    assert nombres  # sanity


@pytest.mark.parametrize("ruta", _contextos(), ids=lambda p: p.parent.name)
def test_toda_clave_de_porcion_nombra_su_poblacion(ruta):
    fuente = ruta.read_text(encoding="utf-8")
    lineas = fuente.splitlines()
    arbol = ast.parse(fuente)

    faltantes = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Dict):
            continue
        for clave in nodo.keys:
            if not isinstance(clave, ast.Constant) or not isinstance(clave.value, str):
                continue
            nombre = clave.value.lower()
            if not any(p in nombre for p in _PORCION):
                continue
            if any(s in nombre for s in _SUJETOS):
                continue
            # Exención declarada en la línea de la clave o en el BLOQUE DE COMENTARIO
            # contiguo de arriba. Mirar solo la línea anterior obligaba a poner el marcador
            # en el último renglón del comentario, que es donde nadie lo escribe: la razón
            # va primero y el detalle después.
            # La exención se declara sobre el DICT, no sobre cada clave: en un literal de
            # varias líneas las claves de continuación no tienen comentario propio y exigirlo
            # por clave obliga a repetir la misma razón en cada renglón.
            if _exento(lineas, clave.lineno) or _exento(lineas, nodo.lineno):
                continue
            faltantes.append(f"{ruta.relative_to(RAIZ)}:{clave.lineno} → '{clave.value}'")

    assert not faltantes, (
        "Estas claves de contexto afirman una porción sin decir de qué población. El modelo "
        "las reatribuye al sujeto más cercano —así se publicó «cuatro compañías concentran el "
        "87,1%» cuando eran cuatro ramos—. Renombrá incluyendo la población, o declará "
        f"`# {_EXENCION} <razón>`:\n  " + "\n  ".join(faltantes))


def test_la_regla_detecta_el_caso_real_que_la_motivo(tmp_path):
    """Un test estructural que no falla ante su propio caso original no protege nada."""
    malo = tmp_path / "ai_context.py"
    malo.write_text('def f():\n    return {"concentracion_top4_pct": 87.1}\n', encoding="utf-8")
    arbol = ast.parse(malo.read_text(encoding="utf-8"))
    claves = [k.value for n in ast.walk(arbol) if isinstance(n, ast.Dict)
              for k in n.keys if isinstance(k, ast.Constant)]
    sospechosas = [c for c in claves
                   if any(p in c.lower() for p in _PORCION)
                   and not any(s in c.lower() for s in _SUJETOS)]
    assert sospechosas == ["concentracion_top4_pct"]
