"""Ninguna operación CON CADENCIA puede bajar el cubo de carteras completo.

El defecto que esto previene. El sync entero de la SIB tarda unas dos horas y media, casi
todas transmitiendo el cubo de créditos. Un deploy de Railway reinicia el worker y mata lo
que esté en vuelo: el 2026-08-29 murió en el trimestre 14 de 22 y no dejó nada. Y
`seed_default_schedules` **activa sola** toda operación recurrente en el próximo despliegue
—su propio docstring dice que existe para que «un deploy nuevo corra todas las syncs
solo»—. Combinar las dos cosas es garantizar que cada semana se lance un trabajo de horas
que el siguiente deploy parte a la mitad.

La regla. Una operación agendada tiene que ser corta o reanudable. Si llama a
`run_backfill`, debe pasar `skip_carteras=True`; el cubo se trae por
`cartera-sectorial-al-dia`, que procesa un trimestre por corrida y recomputa su brecha
contra la base, así que una interrupción cuesta minutos y la siguiente pasada retoma sola.
"""

import ast
import pathlib

import pytest

_FUENTE = pathlib.Path("modules/banking_score/operations.py")


def _agendadas() -> dict:
    """{nombre de operación: nombre del runner} para las que tienen cadencia > 0."""
    from shared.operations import OPERATIONS
    import modules.banking_score.operations  # noqa: F401 — registra las de este módulo
    arbol = ast.parse(_FUENTE.read_text())
    runners = {}
    for n in ast.walk(arbol):
        if not (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "register_operation"):
            continue
        op = n.args[0]
        if not isinstance(op, ast.Call):   # acota el tipo para mypy y salta formas raras
            continue
        primero = op.args[0]
        if not (isinstance(primero, ast.Constant) and isinstance(primero.value, str)):
            continue
        nombre = primero.value
        # el runner es el primer argumento que es un Name (una función)
        fn = next((a.id for a in op.args if isinstance(a, ast.Name)), None)
        o = OPERATIONS.get(nombre)
        if o is not None and o.default_interval_hours > 0 and not o.needs_params and fn:
            runners[nombre] = fn
    return runners


def test_el_barrido_encuentra_operaciones_agendadas():
    """Una aserción de ausencia pasa sola: si el criterio deja de detectar, el test de abajo
    aprueba un módulo sin operaciones."""
    ag = _agendadas()
    assert len(ag) >= 3, f"solo se detectaron {ag}"
    assert "sib-sync-liviano" in ag


@pytest.mark.parametrize("caso", sorted(_agendadas().items()), ids=lambda c: c[0])
def test_ninguna_agendada_baja_el_cubo_completo(caso):
    nombre, runner = caso
    arbol = ast.parse(_FUENTE.read_text())
    fn = next((n for n in ast.walk(arbol)
               if isinstance(n, ast.FunctionDef) and n.name == runner), None)
    assert fn is not None, f"no se encontró el runner {runner}"
    for c in ast.walk(fn):
        if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "run_backfill":
            salta = any(k.arg == "skip_carteras" and k.value.value is True for k in c.keywords)
            assert salta, (
                f"«{nombre}» está agendada y llama a `run_backfill` sin `skip_carteras=True`: "
                f"son ~2h30 de cubo que el próximo deploy parte a la mitad. El cubo se trae "
                f"por `cartera-sectorial-al-dia`, un trimestre por corrida.")
