"""Re-etiquetado RETROACTIVO de las acciones de rating a Perfil SDQ (spec §9).

Decisión del dueño (2026-08-11): el histórico se re-etiqueta, no se corta por fecha.

**Qué significa re-etiquetar cuando no hay traducción.** Un símbolo único (`SDQ-AA+`) no se
mapea a una etiqueta nueva: se reemplaza por dos ejes. Así que una acción tampoco se traduce
— se DESDOBLA en dos transiciones independientes. Una entidad puede mejorar en Ejecución y
deteriorarse en Resiliencia en el mismo período, algo que el tier único no podía expresar
porque los promediaba en un solo movimiento.

**Por qué no hay que recalcular nada.** El backfill de Perfil SDQ dejó `banda_ejecucion` y
`banda_resiliencia` en los 1.789 ratings de los 22 períodos. Las transiciones se derivan de
ese dato ya persistido: esto es re-lectura del histórico, no re-scoring. Recalcular scores
habría producido movimientos de banda entre períodos que nunca ocurrieron.
"""
from typing import Any, Dict, List, Optional, cast


def transicion(previa: Optional[str], nueva: Optional[str]) -> Optional[str]:
    """``"Competitiva → Rezagada"``, o ``None`` si falta alguno de los dos extremos.

    Una banda ausente NO se lee como "sin cambio": si el período anterior no tiene el eje
    calculado, no hay transición que afirmar. Declarar la brecha, no rellenarla.
    """
    if previa is None or nueva is None:
        return None
    return f"{previa} → {nueva}" if previa != nueva else f"{previa} (sin cambio)"


def _delta(previo: Optional[float], nuevo: Optional[float]) -> Optional[float]:
    if previo is None or nuevo is None:
        return None
    return round(float(nuevo) - float(previo), 2)


def reetiquetar(db, set_phase=None) -> Dict[str, Any]:
    """Puebla las columnas por eje de ``rating_actions`` desde los ratings ya persistidos.

    Idempotente: se puede re-correr. No toca ``previous_tier``/``new_tier`` — la notación
    vieja queda como linaje del dato, no como superficie.
    """
    from modules.banking_score.models.models import RatingAction, RatingResult

    set_phase = set_phase or (lambda _m: None)
    set_phase("Leyendo el histórico de acciones")

    acciones: List[RatingAction] = (db.query(RatingAction)
                                    .order_by(RatingAction.period_end).all())
    if not acciones:
        return {"acciones": 0, "reetiquetadas": 0, "sin_par": 0}

    # Índice (bank_id, period_end) → ratings, en una sola consulta: recorrer 1.789 ratings
    # con un query por acción sería N+1 sobre 22 períodos.
    set_phase("Indexando ratings por entidad y período")
    idx: Dict[tuple, Any] = {}
    for r in db.query(RatingResult).all():
        idx[(str(r.bank_id), r.period_end)] = r

    set_phase(f"Re-etiquetando {len(acciones)} acciones")
    tocadas = sin_par = 0
    for a in acciones:
        actual = idx.get((str(a.bank_id), a.period_end))
        previo = (idx.get((str(a.bank_id), a.previous_period_end))
                  if a.previous_period_end else None)
        if actual is None or previo is None:
            sin_par += 1
            continue
        a.banda_ejecucion_previa = previo.banda_ejecucion
        a.banda_ejecucion_nueva = actual.banda_ejecucion
        a.banda_resiliencia_previa = previo.banda_resiliencia
        a.banda_resiliencia_nueva = actual.banda_resiliencia
        # cast: SQLAlchemy tipa las columnas como Column[Decimal] en el modelo, pero el
        # valor asignado es float|None — la conversión la hace el driver.
        a.ejecucion_delta = cast(Any, _delta(previo.ejecucion_score, actual.ejecucion_score))
        a.resiliencia_delta = cast(Any, _delta(previo.resiliencia_score,
                                               actual.resiliencia_score))
        tocadas += 1

    db.commit()
    set_phase("Completado")
    return {
        "acciones": len(acciones),
        "reetiquetadas": tocadas,
        # Una acción sin su par de ratings no se inventa: queda sin ejes y se reporta.
        "sin_par": sin_par,
    }
