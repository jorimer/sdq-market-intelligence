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


def _run_sfc_sync(params, user_id, set_phase) -> Dict:
    from modules.regional_banking.sfc_sync import sfc_sync
    db = SessionLocal()
    try:
        return sfc_sync(db, set_phase=set_phase)
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
    register_operation(Operation(
        "sfc-colombia-sync", "Sincronizar SFC Colombia (sistema)",
        "Agrega el sistema bancario colombiano a partir del dato por entidad que publica "
        "la Superintendencia Financiera en datos.gov.co: solvencia (Σ patrimonio técnico / "
        "Σ activos ponderados por riesgo, nunca el promedio de los ratios) y morosidad "
        "(saldo menos vigente, sin sumar los buckets, que se solapan). Mensual, rezago "
        "~2 meses.",
        _run_sfc_sync, default_interval_hours=720,
    ))


register()
