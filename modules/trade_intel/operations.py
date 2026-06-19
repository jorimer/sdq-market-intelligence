"""Trade-intel console operations — DGA customs trade sync + Gate-E backtest."""
import json
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

BACKTEST_KEY = "trade_backtest_report"


def _run_dga_trade_sync(params, user_id, set_phase) -> Dict:
    from modules.trade_intel.dga_sync import dga_trade_sync
    db = SessionLocal()
    try:
        return dga_trade_sync(db, set_phase=set_phase,
                              only_latest=bool((params or {}).get("only_latest")))
    finally:
        db.close()


def _run_trade_backtest(params, user_id, set_phase) -> Dict:
    """Recompute the resilience backtest from the committed Comtrade+WDI panel and
    persist the report. Deterministic (reads the versioned fixture, no network)."""
    from modules.trade_intel.validation.report import build_backtest_report
    from shared.settings.models import AppSetting

    set_phase("reconstruyendo panel regional de resiliencia + outcomes de shock externo")
    rep = build_backtest_report()
    rep["generated_at"] = datetime.now(timezone.utc).isoformat()

    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_KEY).first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=BACKTEST_KEY, value=payload, is_secret=False))
        db.commit()
    finally:
        db.close()

    prim = rep.get("export_collapse", {})
    return {
        "gini_colapso_export": prim.get("gini"),
        "n_obs": prim.get("n_observations"),
        "n_eventos": prim.get("n_events"),
        "monotonic": prim.get("monotonic"),
        "n_paises": rep.get("n_countries"),
    }


def register() -> None:
    register_operation(Operation(
        "dga-trade-sync", "Sincronizar comercio (Aduanas/DGA)",
        "Descarga las estadísticas de comercio exterior por capítulo arancelario de "
        "la DGA (Data Cruda, exportaciones + importaciones, trimestral) y persiste un "
        "snapshot de resiliencia comercial por trimestre. Dato público real. Usa "
        "{\"only_latest\": true} para refrescar solo el último trimestre.",
        _run_dga_trade_sync, default_interval_hours=2160,  # trimestral → cadencia larga
    ))
    register_operation(Operation(
        "trade-backtest", "Backtest de resiliencia comercial (validación)",
        "Reconstruye la resiliencia comercial histórica en un panel amplio "
        "LatAm+Caribe (24 países, UN Comtrade) y la valida contra shocks externos "
        "realizados (cuenta corriente / reservas / recesión, WDI) + colapso de "
        "exportaciones como contraste. Direccional. Recalcula desde el panel "
        "commiteado, sin red.",
        _run_trade_backtest, default_interval_hours=720,
    ))


register()
