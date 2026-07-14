"""Operación de consola del padrón DGII de contribuyentes por subclase (§B).

Registra ``dgii-contribuyentes-sync``: descarga el padrón público, agrega por subclase y
persiste el corte. Cadencia **manual** (``default_interval_hours=0`` → no auto-agendada):
DGII no declara periodicidad y no se promete frescura hasta confirmarla (§B.3). El dueño la
dispara desde la consola cuando sube un corte nuevo.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_dgii_contribuyentes_sync(params, user_id, set_phase) -> Dict:
    from shared.reference.dgii_sync import dgii_contribuyentes_sync
    db = SessionLocal()
    try:
        set_phase("descargando padrón de contribuyentes DGII")
        return dgii_contribuyentes_sync(db)
    finally:
        db.close()


register_operation(Operation(
    name="dgii-contribuyentes-sync",
    label="DGII · Contribuyentes por subclase",
    description=("Descarga el padrón público de contribuyentes activos de DGII, lo agrega a "
                 "nivel de subclase CIIU (no las filas crudas) y persiste el corte con "
                 "historia. Alimenta el motor de research con el conteo real de participantes "
                 "por vertical (comida rápida, hoteles, supermercados, farmacias…). On-demand. "
                 "Correr cuando: la DGII publique un corte nuevo del padrón de contribuyentes."),
    runner=_run_dgii_contribuyentes_sync,
    default_interval_hours=0,   # manual — no auto-agendada
))
