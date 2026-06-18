"""Trade-intel console operations — registers the DGA customs trade sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_dga_trade_sync(params, user_id, set_phase) -> Dict:
    from modules.trade_intel.dga_sync import dga_trade_sync
    db = SessionLocal()
    try:
        return dga_trade_sync(db, set_phase=set_phase,
                              only_latest=bool((params or {}).get("only_latest")))
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "dga-trade-sync", "Sincronizar comercio (Aduanas/DGA)",
        "Descarga las estadísticas de comercio exterior por capítulo arancelario de "
        "la DGA (Data Cruda, exportaciones + importaciones, trimestral) y persiste un "
        "snapshot de resiliencia comercial por trimestre. Dato público real. Usa "
        "{\"only_latest\": true} para refrescar solo el último trimestre.",
        _run_dga_trade_sync, default_interval_hours=2160,  # trimestral → cadencia larga
    ))


register()
