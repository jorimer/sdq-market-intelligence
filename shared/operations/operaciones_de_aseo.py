"""Operación de consola: el aseo de los directorios de salida.

Semanal y sin parámetros obligatorios. Se agenda sola al desplegar, que es el punto: barrer
a mano cuando el disco llega al 94% no evita la próxima vez.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_aseo(params, user_id, set_phase) -> Dict:  # noqa: ARG001
    """Barre `data/charts` y `data/reports` según la retención declarada.

    Con `simulacro: true` cuenta sin borrar — es como se comprueba una tarea destructiva
    antes de dejarla suelta, y por eso el parámetro es del console y no del código.
    """
    from shared.operations.aseo import _libre_en_disco, run_aseo

    simulacro = bool((params or {}).get("simulacro"))
    antes = _libre_en_disco()
    db = SessionLocal()
    try:
        r = run_aseo(simulacro=simulacro, db=db, progreso=set_phase)
    finally:
        db.close()
    despues = _libre_en_disco()
    # El disco libre ANTES y DESPUÉS, porque es la única cifra que dice si sirvió. Un
    # «borré 3.502 archivos» sin eso no distingue una limpieza útil de una que no movió nada.
    return {**r, "gb_libres_antes": antes, "gb_libres_despues": despues}


register_operation(Operation(
    "aseo-directorios-de-salida", "Aseo de gráficos e informes generados",
    "Borra los gráficos y los informes generados que superan su ventana de retención "
    "(7 días los PNG, 90 los PDF). Los gráficos son temporales por construcción: se "
    "embeben en el PDF y nadie vuelve a mirarlos. Los informes que solo viven en disco "
    "—sin `file_blob`— quedan PROTEGIDOS por referencia, tengan la edad que tengan. "
    "Pasar `simulacro: true` para contar sin borrar.",
    _run_aseo,
    # SEMANAL. Más seguido no aporta —la basura se acumula en días, no en horas— y más
    # espaciado deja que un mes malo llene el disco antes del próximo barrido.
    default_interval_hours=168,
))
