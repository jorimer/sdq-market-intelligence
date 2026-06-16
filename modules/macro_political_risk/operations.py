"""Macro-political-risk console operations — registers wgi-sync.

Owns the WGI sync runner and registers it into the shared operation console
(:mod:`shared.operations`), so it's triggerable / monitorable / schedulable from
the UI alongside every other module's operations.
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_wgi_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.wgi_sync import wgi_sync
    db = SessionLocal()
    try:
        return wgi_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_wdi_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_political_risk.wdi_sync import wdi_sync
    db = SessionLocal()
    try:
        return wdi_sync(db, set_phase=set_phase)
    finally:
        db.close()


_PEER_NAMES = {"DO": "República Dominicana", "CR": "Costa Rica", "PA": "Panamá",
               "GT": "Guatemala", "JM": "Jamaica"}
_PEER_REGIONS = {"DO": "Caribe", "CR": "Centroamérica", "PA": "Centroamérica",
                 "GT": "Centroamérica", "JM": "Caribe"}


def _run_irmp_snapshot(params, user_id, set_phase) -> Dict:
    """Assemble the IRMP dataset (real + declared rubric) and compute+persist a
    snapshot for every peer country at the latest period, publishing irmp.updated.
    """
    from datetime import date
    from modules.macro_political_risk.service import assemble_irmp_dataset, compute_and_persist
    db = SessionLocal()
    try:
        set_phase("ensamblando dataset (real + rúbrica)")
        asm = assemble_irmp_dataset(db)
        dataset = asm["dataset"]
        period = asm["period"]
        # Require real data: an all-rubric snapshot isn't useful for the backtest
        # or the outlook overlay, and without a live period we'd otherwise date the
        # snapshot to a future year-end. Sync WGI/WDI first.
        if not asm["has_live"] or not (period and str(period).isdigit()):
            return {"snapshots": 0, "countries": len(dataset), "has_live": asm["has_live"],
                    "errors": ["sin dato real persistido; corre wgi-sync/wdi-sync primero"]}
        period_end = date(int(period), 12, 31)
        snaps, errors = 0, []
        for i, iso in enumerate(sorted(dataset), 1):
            set_phase(f"calculando IRMP {iso} ({i}/{len(dataset)})")
            try:
                compute_and_persist(
                    db, country_code=iso, dataset=dataset, period_end=period_end,
                    country_name=_PEER_NAMES.get(iso), region=_PEER_REGIONS.get(iso),
                )
                snaps += 1
            except Exception as e:  # noqa: BLE001 — one country must not abort the batch
                errors.append(f"{iso}: {e}")
        return {"snapshots": snaps, "period": str(period_end),
                "countries": len(dataset), "has_live": asm["has_live"], "errors": errors}
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "wgi-sync", "Sincronizar WGI (Banco Mundial)",
        "Trae los 3 indicadores de gobernanza (rule of law / gov effectiveness / "
        "control of corruption) para el peer set regional y los persiste.",
        _run_wgi_sync, default_interval_hours=720,  # WGI es anual → cadencia larga
    ))
    register_operation(Operation(
        "wdi-sync", "Sincronizar WDI + IMF (macro)",
        "Trae los indicadores macro/externos (PIB, inflación, reservas, cuenta "
        "corriente, IED desde WDI; deuda y balance fiscal desde IMF WEO) para el "
        "peer set regional y los persiste.",
        _run_wdi_sync, default_interval_hours=720,  # anual → cadencia larga
    ))
    register_operation(Operation(
        "irmp-snapshot", "Calcular snapshot IRMP",
        "Ensambla el dataset (dato real + rúbrica declarada) y calcula+persiste el "
        "IRMP de cada país del peer set para el último período, publicando "
        "irmp.updated para los demás ejes.",
        _run_irmp_snapshot, default_interval_hours=720,
    ))


register()
