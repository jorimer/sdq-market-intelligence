"""Sector-intel console operations — registers bcrd-sectores-sync.

Registers the BCRD value-added sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI alongside every other module's operations (Gate F from day one).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_bcrd_sectores_sync(params, user_id, set_phase) -> Dict:
    from modules.sector_intel.sectors_sync import bcrd_sectores_sync
    db = SessionLocal()
    try:
        return bcrd_sectores_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_sector_snapshot(params, user_id, set_phase) -> Dict:
    """Assemble the IAI dataset (real BCRD + contract macro + declared rubric) and
    compute+persist the IAI/SGPS for every sector, publishing sector.updated."""
    from datetime import date

    from modules.sector_intel.service import assemble_iai_dataset, compute_and_persist
    db = SessionLocal()
    try:
        set_phase("ensamblando dataset (real + rúbrica)")
        asm = assemble_iai_dataset(db)
        period = asm["period"] or str(date.today().year)
        set_phase(f"calculando IAI/SGPS de {len(asm['dataset'])} sectores")
        res = compute_and_persist(
            db, period=period, sector_dataset=asm["dataset"], sgps_inputs=asm["sgps_inputs"],
        )
        live_dims = sum(
            1 for smap in asm["sources"].values() for v in smap.values() if v == "live"
        )
        return {"sectors": len(res["sectors"]), "period": period,
                "has_live": asm["has_live"], "valores_en_vivo": live_dims, "errors": []}
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "bcrd-sectores-sync", "Sincronizar sectores (BCRD · valor agregado)",
        "Trae el valor agregado por actividad económica del BCRD (PIB por sectores "
        "de origen, base 2018): tamaño (share del VAB) y crecimiento real interanual "
        "para los ~17 sectores de la economía, y los persiste para el IAI.",
        _run_bcrd_sectores_sync, default_interval_hours=2160,  # cuentas nac. ~trimestral → trimestral
    ))
    register_operation(Operation(
        "sector-snapshot", "Calcular snapshot sectorial (IAI/SGPS)",
        "Ensambla el dataset por sector (dato real del BCRD + exposición macro del "
        "contrato + rúbrica declarada) y calcula+persiste el IAI/SGPS de los ~17 "
        "sectores para el último período, publicando sector.updated.",
        _run_sector_snapshot, default_interval_hours=2160,
    ))


register()
