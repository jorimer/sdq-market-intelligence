"""Regla estructural: toda consulta a ``insurance_series`` POR ENTIDAD pasa por el mapa canónico.

Las series se guardan bajo el slug DERIVADO del nombre de hoja del Excel auditado, que Excel
trunca a 31 caracteres. Consultar por el slug canónico devuelve CERO filas en silencio.

El defecto apareció **cuatro veces** en este módulo —cada vez en el motor que faltaba— y
ningún test unitario lo agarra, porque cada pieza funciona por separado. Esto lo hace cumplir
leyendo el código: si una consulta por entidad no invoca ``_canon_map``, hay que marcarla
como exenta con una razón, no dejarla pasar en silencio.
"""
import ast
import pathlib

import pytest

_RAIZ = pathlib.Path(__file__).resolve().parents[1]
_MARCA = "canon-exento:"


def _funciones_con_consulta_por_entidad():
    """(archivo, función, fuente) de cada def que consulta InsuranceSeries por entidad."""
    out = []
    for py in sorted(_RAIZ.rglob("*.py")):
        if "/tests/" in str(py).replace("\\", "/"):
            continue
        texto = py.read_text(encoding="utf-8")
        if "InsuranceSeries" not in texto or "entity_slug" not in texto:
            continue
        try:
            arbol = ast.parse(texto)
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            src = ast.get_source_segment(texto, nodo) or ""
            if "InsuranceSeries" not in src or "entity_slug" not in src:
                continue
            # La regla aplica a las LECTURAS QUE CRUZAN ENTIDADES: `entity_slug.isnot(None)`
            # o `.in_(...)`. Quedan fuera por construcción:
            #   · `entity_slug.is_(None)`  → espina de mercado, no hay entidad que canonizar
            #   · `entity_slug == <slug>`  → escritura (upsert) o lookup de una entidad ya
            #     resuelta por quien llama; ahí el slug derivado es justamente el correcto,
            #     porque es el que la ingesta acaba de persistir.
            cruza = ("entity_slug.isnot(None)" in src
                     or "entity_slug.in_(" in src)
            if not cruza:
                continue
            out.append((py.relative_to(_RAIZ.parent.parent), nodo.name, src))
    return out


def test_hay_consultas_por_entidad_que_vigilar():
    """Si esto falla, la regla dejó de aplicar a algo y hay que revisar por qué."""
    assert _funciones_con_consulta_por_entidad(), "no se detectó ninguna consulta por entidad"


@pytest.mark.parametrize(
    "archivo,funcion,src",
    _funciones_con_consulta_por_entidad(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_toda_consulta_por_entidad_canoniza_o_declara_su_excepcion(archivo, funcion, src):
    if "_canon_map" in src:
        return
    assert _MARCA in src, (
        f"{archivo}::{funcion} consulta insurance_series por entity_slug sin pasar por "
        f"_canon_map. Las series están bajo el slug DERIVADO (Excel trunca los nombres de "
        f"hoja a 31 caracteres), así que consultar por el canónico devuelve cero filas EN "
        f"SILENCIO — pasó cuatro veces en este módulo. Si la consulta no lo necesita, "
        f"marcala con un comentario «{_MARCA} <razón>»."
    )
    razon = src.split(_MARCA, 1)[1].strip().splitlines()[0].strip()
    assert len(razon) >= 15, f"{archivo}::{funcion} se declara exenta sin una razón legible"
