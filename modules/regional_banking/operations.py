"""Operaciones de consola del módulo regional."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations.service import Operation, register_operation


def _run_secmca_sync(params, user_id, set_phase) -> Dict:
    from modules.regional_banking.secmca_sync import secmca_sync
    db = SessionLocal()
    try:
        return secmca_sync(db, set_phase=set_phase)
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "secmca-sync", "Sincronizar SECMCA / EMFA (7 plazas)",
        "Descarga los cuadros EMFA del CMCA publicados en secmca.org y persiste crédito "
        "al sector privado por destino y tasas bancarias activa y pasiva en moneda "
        "nacional, para Costa Rica, El Salvador, Guatemala, Honduras, Nicaragua, Panamá y "
        "República Dominicana. Es la única fuente armonizada del boletín regional. "
        "Mensual, con rezago desigual por país.",
        _run_secmca_sync, default_interval_hours=720,
    ))


register()
