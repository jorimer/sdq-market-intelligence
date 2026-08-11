"""Deduplicación de ``rating_actions`` — una acción por entidad y período.

**Los duplicados no son historia: son la misma acción recalculada.** ``rating_results`` tiene
restricción de unicidad y se ACTUALIZA en cada rescore; ``rating_actions`` no la tenía y se
AGREGABA. Medido en producción: 35.621 filas contra ~1.870 pares (entidad, período) posibles,
o sea unas 19 copias por evento — una por cada rescore corrido en la vida del proyecto.

No hay nada que conservar en las copias viejas:

* Ninguna se emitió como evento separado. Un comunicado se cuelga de una fila concreta
  (``communique_report_id``) y en producción **no hay ningún comunicado emitido**, así que
  deduplicar no huerfana ningún documento entregado a un cliente.
* El argumento de "conservar lo que dijimos en su momento" no aplica: el rating de cada
  período TAMBIÉN está sobrescrito con la metodología vigente. Guardar acciones viejas
  dejaría transiciones que no corresponden a los ratings que tienen al lado.
* La trazabilidad de por qué cambió una banda se conserva en la marca ``metodologica``.

La función **cuenta primero y borra después**, y `ejecutar=False` es el valor por defecto:
un borrado en producción se mira antes de correrlo.
"""
from typing import Any, Dict, List


def plan_de_dedup(db) -> Dict[str, Any]:
    """Qué se borraría, sin borrar nada. La fila que sobrevive es la MÁS RECIENTE."""
    from modules.banking_score.models.models import RatingAction

    filas: List[Any] = (db.query(RatingAction)
                        .order_by(RatingAction.bank_id, RatingAction.period_end,
                                  RatingAction.created_at.desc()).all())
    por_par: Dict[tuple, List[Any]] = {}
    for a in filas:
        por_par.setdefault((str(a.bank_id), a.period_end), []).append(a)

    sobreviven = len(por_par)
    a_borrar: List[str] = []
    con_comunicado = 0
    for grupo in por_par.values():
        # `created_at desc` deja la más reciente primero. Si alguna del grupo tiene un
        # comunicado emitido, ESA sobrevive: es la que se le entregó a un cliente.
        con_com = [x for x in grupo if x.communique_report_id]
        con_comunicado += len(con_com)
        keep = con_com[0] if con_com else grupo[0]
        a_borrar += [str(x.id) for x in grupo if x.id != keep.id]

    return {
        "total": len(filas),
        "pares_unicos": sobreviven,
        "a_borrar": len(a_borrar),
        "con_comunicado_emitido": con_comunicado,
        "ids_a_borrar": a_borrar,
    }


def deduplicar(db, set_phase=None, ejecutar: bool = False) -> Dict[str, Any]:
    """Cuenta siempre; borra solo con ``ejecutar=True``."""
    from modules.banking_score.models.models import RatingAction

    set_phase = set_phase or (lambda _m: None)
    set_phase("Contando duplicados")
    plan = plan_de_dedup(db)
    ids = plan.pop("ids_a_borrar")

    if not ejecutar:
        set_phase("Simulación — no se borró nada")
        return {**plan, "ejecutado": False}

    set_phase(f"Borrando {len(ids)} duplicados")
    borradas = 0
    for i in range(0, len(ids), 500):  # por lotes: 34 mil DELETE en una sentencia no va
        lote = ids[i:i + 500]
        borradas += (db.query(RatingAction)
                     .filter(RatingAction.id.in_(lote))
                     .delete(synchronize_session=False))
    db.commit()
    set_phase("Completado")
    return {**plan, "ejecutado": True, "borradas": borradas}
