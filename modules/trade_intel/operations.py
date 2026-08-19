"""Trade-intel console operations — DGA customs trade sync + Gate-E backtest."""
import json
from datetime import datetime, timezone
from typing import Dict, Optional

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.validation.frescura import (
    MotorValidacion, huella_archivo, registrar_motor,
)

BACKTEST_KEY = "trade_backtest_report"


def huella_backtest(_db) -> Dict:
    """Estado del insumo del backtest de comercio: el panel Comtrade+WDI COMITEADO.

    Es el único motor del catálogo cuyo insumo es enteramente determinístico —un fixture en
    el árbol— así que la huella lo cubre entero: si el panel se regenera, el reporte queda
    marcado obsoleto sin que haga falta recordar recalcularlo.
    """
    from shared.data import comtrade_client as cc
    from modules.trade_intel.validation.peers import VALIDATION_PEERS

    return {"panel_comtrade": huella_archivo(cc._FIXTURES_DIR / cc.FIXTURE_FILE),
            "peers": sorted(VALIDATION_PEERS)}


def _run_partner_chapters_sync(params, user_id, set_phase) -> Dict:
    """Ingiere socio × capítulo desde Comtrade (anual)."""
    from modules.trade_intel.partner_chapters_sync import sync_partner_chapters

    años = params.get("years") or [datetime.now(timezone.utc).year - y for y in (1, 2, 3)]
    db = SessionLocal()
    try:
        return sync_partner_chapters(db, sorted(int(a) for a in años), set_phase=set_phase,
                                     forzar=bool(params.get("forzar")))
    finally:
        db.close()


def _periodo_chapters(db) -> Optional[str]:
    """Último año de socio × capítulo ingerido, para que la agenda sepa si va atrasada."""
    from modules.trade_intel.models.models import TradePartnerChapter
    try:
        r = (db.query(TradePartnerChapter.period)
             .order_by(TradePartnerChapter.period.desc()).first())
        return r[0] if r else None
    except Exception:  # noqa: BLE001 — jamás romper la agenda por esta lectura
        return None


def _periodo_cargado(db) -> Optional[str]:
    """El último período de comercio INGERIDO ("2026-Q1"), o None.

    Es lo que permite al scheduler saber que vamos atrasados: si la DGA ya publicó 2026-Q2 y
    acá sigue diciendo 2026-Q1, la próxima corrida se agenda en días y no en el trimestre
    siguiente.
    """
    from modules.trade_intel.models.models import TradeScore
    try:
        r = db.query(TradeScore).order_by(TradeScore.period.desc()).first()
        return r.period if r else None
    except Exception:  # noqa: BLE001 — jamás romper la agenda por esta lectura
        return None


def _run_dga_trade_sync(params, user_id, set_phase) -> Dict:
    from modules.trade_intel.dga_sync import dga_trade_sync
    db = SessionLocal()
    try:
        return dga_trade_sync(db, set_phase=set_phase,
                              only_latest=bool((params or {}).get("only_latest")))
    finally:
        db.close()


def _run_dga_partners_sync(params, user_id, set_phase) -> Dict:
    from modules.trade_intel.partners_sync import dga_partners_sync
    db = SessionLocal()
    try:
        return dga_partners_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_trade_backtest(params, user_id, set_phase) -> Dict:
    """Recompute the resilience backtest from the committed Comtrade+WDI panel and
    persist the report. Deterministic (reads the versioned fixture, no network)."""
    from modules.trade_intel.validation.report import build_backtest_report
    from shared.settings.models import AppSetting

    from shared.validation.frescura import sellar

    set_phase("reconstruyendo panel regional de resiliencia + outcomes de shock externo")
    rep = build_backtest_report()

    db = SessionLocal()
    try:
        sellar(rep, "trade_intel", db)
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
        _run_dga_trade_sync, default_interval_hours=2160, anclaje="trimestral",
        periodo_actual=_periodo_cargado,  # trimestral → cadencia larga
    ))
    register_operation(Operation(
        "dga-partners-sync", "Sincronizar comercio por país socio (Aduanas/DGA)",
        "Consulta el comercio exterior por país socio (exportaciones e importaciones, "
        "FOB USD, trimestral) desde el Power BI de la DGA y persiste el top de socios "
        "por flujo y trimestre. Complementa el corte por capítulo arancelario con la "
        "dimensión geográfica. Dato público real; idempotente por país×flujo×trimestre.",
        _run_dga_partners_sync, default_interval_hours=2160, anclaje="trimestral",
        periodo_actual=_periodo_cargado,  # trimestral → cadencia larga
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

    registrar_motor(MotorValidacion(
        eje="trade_intel", operacion="trade-backtest", clave=BACKTEST_KEY,
        partes=huella_backtest,
        sin_cascada_motivo=(
            "el panel de validación es un fixture comiteado que se regenera por script "
            "(`scripts/build_comtrade_fixture.py`), no por una operación de consola. La "
            "huella cubre el fixture entero, así que un panel nuevo marca el reporte "
            "obsoleto en la propia respuesta."),
    ))


register()

register_operation(
    Operation(
        "comtrade-partner-chapters-sync",
        "Sincronizar comercio bilateral por capítulo (Comtrade)",
        "Qué bienes importa RD de cada socio, abierto por capítulo HS. Es el cruce que la "
        "DGA no publica —su Excel no trae país de origen— y que el motor de Research "
        "declaraba fuera de alcance.",
        _run_partner_chapters_sync,
        default_interval_hours=8760, anclaje="anual",
        periodo_actual=_periodo_chapters,
    )
)
