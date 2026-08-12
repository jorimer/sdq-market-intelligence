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

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

# Palabras que denotan una porción de un total. Una clave con alguna de ellas afirma
# implícitamente «de qué», y ese «de qué» tiene que estar escrito.
_PORCION = ("concentracion", "concentration", "cuota", "share", "participacion", "hhi", "cr5",
            "cr10", "peso_")

# Sujetos admitidos: la población sobre la que se computa la porción.
_SUJETOS = ("ramo", "ramos", "compania", "companias", "empresa", "empresas", "entidad",
            "entidades", "banco", "bancos", "aseguradora", "aseguradoras", "afp", "activos",
            "provincia", "province", "typology", "tipologia", "export", "chapter", "sector",
            "origin", "origen", "region", "generation", "generacion",
            "producto", "product", "geography", "personas", "danos", "salud",
            "sin_clasificar", "broadband", "sqm", "metric", "market", "mercado")

_EXENCION = "sujeto-ok:"


def _contextos():
    return sorted(RAIZ.glob("modules/*/ai_context.py"))


def test_hay_contextos_que_revisar():
    """Si el glob deja de encontrar archivos, el test pasaría vacío y no protegería nada."""
    assert len(_contextos()) >= 10


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
            # Exención declarada en la línea de la clave o en la anterior.
            i = clave.lineno - 1
            ventana = "\n".join(lineas[max(0, i - 1):i + 1])
            if _EXENCION in ventana:
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
