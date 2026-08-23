"""Toda operación registrada respeta la firma con la que el runner la invoca.

**Por qué existe este archivo.** ``service._worker`` invoca ``op.runner(params, user_id,
set_phase)``. El registro no verifica la firma: una operación con dos parámetros se
registra sin queja y solo revienta al EJECUTARLA en producción, con "takes 2 positional
arguments but 3 were given". Le pasó a ``_run_perfil_sdq``, cuya operación
``perfil-sdq-backfill`` no funcionó NUNCA desde que el contrato cambió — nadie se enteró
porque el fallo solo existe en el momento de correrla.

El test que salió de aquel arreglo vivía en ``modules/banking_score/tests/`` y solo miraba
``modules.banking_score.operations``: 12 de los 78 runners del árbol. Los otros 66 quedaban
fuera del glob, que es exactamente la forma en que un defecto entre motores reaparece en el
motor que el test no mira. Este barre el ÁRBOL COMPLETO.

Lee con ``ast`` en vez de importar: un import arrastra dependencias de cada módulo y el
test se vuelve frágil por razones ajenas a lo que verifica. La firma es sintaxis, así que
leerla del fuente alcanza.
"""
import ast
import pathlib

import pytest

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
_FIRMA = ["params", "user_id", "set_phase"]
_EXCLUIDOS = {".venv", "node_modules", ".git", "__pycache__", "frontend"}


def _runners():
    """Todo ``def _run_*`` de nivel superior del árbol, con su archivo y línea."""
    out = []
    for p in sorted(_RAIZ.rglob("*.py")):
        if _EXCLUIDOS & set(p.parts):
            continue
        try:
            arbol = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in arbol.body:
            if (isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and nodo.name.startswith("_run_")):
                out.append((p.relative_to(_RAIZ), nodo.lineno, nodo.name,
                            [a.arg for a in nodo.args.args]))
    return out


def test_el_barrido_encuentra_runners():
    """Un barrido vacío pasa en verde sin proteger nada: si el patrón deja de encontrar
    runners (se renombran, se mueven), este test lo dice en vez de dar un falso verde."""
    encontrados = _runners()
    assert len(encontrados) >= 70, (
        f"el barrido encontró {len(encontrados)} runners; esperaba ~78. "
        "¿Cambió el nombre o la ubicación de las operaciones?")
    modulos = {r[0].parts[0] for r in encontrados}
    assert {"modules", "shared"} <= modulos, f"el barrido no cubre todo el árbol: {modulos}"


@pytest.mark.parametrize("archivo,linea,nombre,args",
                         _runners(),
                         ids=lambda v: str(v) if isinstance(v, (str, int)) else "")
def test_runner_respeta_la_firma(archivo, linea, nombre, args):
    assert args[:3] == _FIRMA, (
        f"{archivo}:{linea} — {nombre}{tuple(args)} no tiene la firma del runner "
        f"{tuple(_FIRMA)}. El registro lo acepta igual y falla al EJECUTARLO en producción.")
