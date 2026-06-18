"""ESG-climate console operations — registers the IRC sync + backtest."""
import json
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

ESG_BACKTEST_KEY = "esg_backtest_report"


def _run_esg_sync(params, user_id, set_phase) -> Dict:
    from modules.esg_climate.service import esg_sync
    db = SessionLocal()
    try:
        return esg_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_esg_backtest(params, user_id, set_phase) -> Dict:
    """Validate the IRC against realized climate-disaster mortality (OWID/EM-DAT)
    and persist the report (AppSetting). Best-effort on the OWID download."""
    from shared.settings.models import AppSetting
    from shared.data.owid_disasters_client import owid_disasters_client
    from modules.esg_climate.service import IRC_PANEL, get_scores
    from modules.esg_climate.validation.backtest import build_esg_backtest
    db = SessionLocal()
    try:
        irc = {r.entity_key: float(r.esg_score) for r in get_scores(db) if r.esg_score is not None}
        if not irc:
            return {"error": "sin IRC; corre esg-sync primero", "errors": ["sin IRC"]}
        set_phase("descargando mortalidad por desastres (OWID/EM-DAT)")
        try:
            mortality = owid_disasters_client.fetch_climate_mortality(list(IRC_PANEL))
        except Exception as e:  # noqa: BLE001 — report the failure, don't crash
            return {"error": f"OWID no disponible: {e}", "errors": [str(e)]}
        set_phase("calculando correlación IRC vs mortalidad climática")
        report = build_esg_backtest(irc, mortality)
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        row = db.query(AppSetting).filter(AppSetting.key == ESG_BACKTEST_KEY).first()
        payload = json.dumps(report)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=ESG_BACKTEST_KEY, value=payload, is_secret=False))
        db.commit()
        return {"spearman": report.get("spearman"), "monotonic": report.get("monotonic"),
                "n_countries": report.get("n_countries"), "errors": []}
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
    register_operation(Operation(
        "esg-backtest", "Backtest del IRC climático",
        "Valida el IRC contra la mortalidad real por desastres climáticos (OWID/"
        "EM-DAT): correlación de Spearman (con IC bootstrap) y monotonía por banda. "
        "Validación direccional preliminar.",
        _run_esg_backtest, default_interval_hours=8760,
    ))


register()
