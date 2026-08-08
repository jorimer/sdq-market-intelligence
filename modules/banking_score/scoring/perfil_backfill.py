"""Recomputa Perfil SDQ sobre el histórico completo de ``rating_results``.

El spec §9 pide "re-etiquetar retroactivamente" el histórico a la notación nueva. **Re-etiquetar
en sentido literal es imposible y sería deshonesto**: no existe un mapeo de ``SDQ-AA+`` a dos
ejes, porque un símbolo único no contiene la información que los dos ejes separan. Traducirlo
inventaría una lectura que nadie calculó.

Lo que sí se puede —y es lo que hace este módulo— es **recomputar**: ``rating_results`` guarda
los 5 sub-componentes de cada período, que son exactamente el insumo de Perfil SDQ. El
resultado no es una traducción del símbolo viejo sino la aplicación de la metodología nueva a
los datos que ya existían, que es lo que el dueño quiso decir al elegir "retroactivo".

Los cortes de Ejecución son **relativos al panel del período**, no globales: comparar la
eficiencia de un banco de 2021 contra los cuartiles de 2026 mediría el paso del tiempo, no su
desempeño. Cada corte se calcula con las entidades de SU período y de su mismo tipo.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, RatingResult
from modules.banking_score.scoring.perfil_sdq import perfil_panel

logger = logging.getLogger("sdq.banking.perfil_backfill")


def _sub_scores(r: RatingResult) -> Dict[str, Optional[float]]:
    def f(v):
        return float(v) if v is not None else None
    return {"solidez": f(r.solidez_score), "calidad": f(r.calidad_score),
            "eficiencia": f(r.eficiencia_score), "liquidez": f(r.liquidez_score),
            "diversificacion": f(r.diversificacion_score)}


def backfill_perfil_sdq(db: Session,
                        set_phase: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Calcula y persiste los dos ejes para TODOS los ``rating_results``, período a período.

    Idempotente: recalcular no cambia nada si los sub-componentes no cambiaron.
    """
    set_phase = set_phase or (lambda _m: None)
    tipos = {b.id: b.bank_type for b in db.query(Bank).all()}

    set_phase("Leyendo el histórico de ratings")
    filas: List[RatingResult] = db.query(RatingResult).all()
    if not filas:
        return {"periodos": 0, "ratings": 0, "note": "sin ratings que recomputar"}

    por_periodo: Dict[Any, List[RatingResult]] = {}
    for r in filas:
        por_periodo.setdefault(r.period_end, []).append(r)

    escritos = 0
    for periodo in sorted(por_periodo):
        panel = por_periodo[periodo]
        set_phase(f"Perfil SDQ {periodo} ({len(panel)} entidades)")
        entradas = [{"_row": r, "entity_type": tipos.get(r.bank_id),
                     "sub_scores": _sub_scores(r)} for r in panel]
        for e in perfil_panel(entradas)["entidades"]:
            row: RatingResult = e["_row"]
            row.ejecucion_score = e["ejecucion"]
            row.resiliencia_score = e["resiliencia"]
            row.banda_ejecucion = e["banda_ejecucion"]
            row.banda_resiliencia = e["banda_resiliencia"]
            escritos += 1
        db.flush()

    db.commit()
    set_phase("Completado")
    logger.info("Perfil SDQ recomputado sobre %d períodos / %d ratings",
                len(por_periodo), escritos)
    return {"periodos": len(por_periodo), "ratings": escritos,
            "desde": str(min(por_periodo)), "hasta": str(max(por_periodo))}
