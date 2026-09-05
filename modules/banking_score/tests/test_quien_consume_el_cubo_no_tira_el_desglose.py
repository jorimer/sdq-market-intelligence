"""Quien consume el escalar del cubo de carteras tiene que manejar también su desglose.

El defecto. `_compute_carteras_metrics` devuelve, por entidad y corte, el HHI sectorial Y el
desglose `por_sector` del que ese HHI sale. Hay DOS caminos que consumen ese resultado —el
backfill (`run_backfill`, vía el mapeo del cliente) y el recómputo puntual
(`recompute_carteras_metrics`)— y la persistencia se cableó solo en el segundo. El backfill
tomaba el `hhi`, tiraba `por_sector`, y la tabla sectorial quedaba vacía. **Nada falló**: el
sync corrió dos horas y media, reportó `completado` sin errores, y el dato no existía.

Es el patrón que este repo ya tiene nombrado —un guard presente en un motor y ausente en el
otro— y la lección escrita no lo evitó: lo cometí igual, en la misma sesión en que arreglé
tres instancias del mismo patrón. Por eso acá va un test que lee el código.

La regla. Toda función que consuma la clave `"hhi"` del resultado del cubo debe también
mencionar el desglose (`por_sector` o `_por_sector`): persistirlo, o reenviarlo a quien
pueda. Un consumidor que solo toma el escalar está descartando el dato en silencio.
"""

import ast
import pathlib

import pytest

_FUENTES = [
    pathlib.Path("modules/banking_score/sib_sync.py"),
    pathlib.Path("shared/data/sib_data_client.py"),
]


def _literales(nodo) -> set:
    return {n.value for n in ast.walk(nodo)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _funciones_que_consumen_el_cubo(arbol):
    for n in ast.walk(arbol):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lits = _literales(n)
        # `_compute_carteras_metrics` PRODUCE el dict; no es un consumidor.
        if "hhi" in lits and n.name != "_compute_carteras_metrics":
            yield n.name, lits


def test_el_barrido_encuentra_los_consumidores():
    """Una aserción de ausencia pasa sola: si el glob o el criterio se rompen, el test de
    abajo aprueba un repo donde nadie consume el cubo."""
    hallados = [nombre for f in _FUENTES
                for nombre, _ in _funciones_que_consumen_el_cubo(ast.parse(f.read_text()))]
    assert len(hallados) >= 2, f"solo se encontraron {hallados}: el criterio dejó de detectar"


@pytest.mark.parametrize("fuente", _FUENTES, ids=lambda f: f.name)
def test_ningun_consumidor_tira_el_desglose(fuente):
    huerfanas = [nombre for nombre, lits in _funciones_que_consumen_el_cubo(ast.parse(fuente.read_text()))
                 if not ({"por_sector", "_por_sector"} & lits)]
    assert not huerfanas, (
        f"{fuente.name}: {huerfanas} consume el `hhi` del cubo y NO menciona el desglose. "
        f"El escalar y `por_sector` salen del mismo recorrido: tomar uno y descartar el otro "
        f"deja la tabla sectorial vacía sin que nada falle.")
