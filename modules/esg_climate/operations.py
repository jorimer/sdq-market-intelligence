"""ESG-climate console operations — registers the IRC sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_esg_sync(params, user_id, set_phase) -> Dict:
    from modules.esg_climate.service import esg_sync
    db = SessionLocal()
    try:
        return esg_sync(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "esg-sync", "Sincronizar IRC climático (ND-GAIN)",
        "Calcula el Índice de Resiliencia Climática (IRC) nacional sobre el panel "
        "Caribe/LatAm con dato real de ND-GAIN (físico/adaptativa/gobernanza); la "
        "transición queda rúbrica hasta cablear energía/PEN. Publica 'esg.updated'.",
        _run_esg_sync, default_interval_hours=8760,  # ND-GAIN es anual
    ))


register()
