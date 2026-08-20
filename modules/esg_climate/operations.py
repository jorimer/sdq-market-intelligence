"""ESG-climate console operations — registers the IRC sync + backtest."""
import json
from datetime import datetime, timezone
from typing import Dict, Optional

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.validation.frescura import MotorValidacion, registrar_motor
from shared.validation.control_tamano import ControlDeTamano

ESG_BACKTEST_KEY = "esg_backtest_report"


def huella_backtest(db) -> Dict:
    """Estado del insumo LOCAL del backtest del IRC: los scores del panel.

    La mortalidad por desastres (OWID/EM-DAT) se descarga en cada corrida y no queda
    persistida, así que la huella no la cubre — se declara en ``insumo_no_cubierto`` y por eso
    el reloj queda como red de seguridad. Afirmar frescura total acá sería la versión
    elegante del mismo defecto.
    """
    from sqlalchemy import func

    from modules.esg_climate.models.models import ESGScore

    r = (db.query(func.count(ESGScore.id), func.max(ESGScore.period),
                  func.sum(ESGScore.esg_score)).one())
    return {"scores_n": r[0], "scores_hasta": r[1], "scores_suma": r[2]}


def _run_esg_sync(params, user_id, set_phase) -> Dict:
    from modules.esg_climate.service import esg_sync
    db = SessionLocal()
    try:
        return esg_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _poblacion_del_panel(iso3_codes) -> Optional[Dict[str, float]]:
    """``{iso3: población}`` del WDI, o ``None`` si la descarga falla.

    Devolver ``None`` y que el reporte lo DECLARE es distinto de devolver un dict vacío, que
    se leería como «ningún país tiene población».
    """
    from shared.data.wdi_client import fetch_wb_indicator

    try:
        filas, _actualizado = fetch_wb_indicator("SP.POP.TOTL", list(iso3_codes), mrv=1)
    except Exception:  # noqa: BLE001 — el control es best-effort, no tumba el backtest
        return None
    out: Dict[str, float] = {}
    for fila in filas or []:
        iso3 = (fila.get("countryiso3code") or "").upper()
        valor = fila.get("value")
        if iso3 and valor is not None:
            out[iso3] = float(valor)
    return out or None


def _run_esg_backtest(params, user_id, set_phase) -> Dict:
    """Validate the IRC against realized climate-disaster mortality (OWID/EM-DAT)
    and persist the report (AppSetting). Best-effort on the OWID download."""
    from shared.settings.models import AppSetting
    from shared.data.owid_disasters_client import owid_disasters_client
    from modules.esg_climate.service import IRC_PANEL, get_scores
    from modules.esg_climate.validation.backtest import build_esg_backtest
    from shared.validation.frescura import sellar
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
        # El CONTROL POR TAMAÑO necesita la población: el desenlace viene por 100.000
        # habitantes, así que la población es su deflactor. Best-effort como la descarga de
        # OWID — si el WDI no responde, el control se declara no computado en vez de
        # desaparecer, y el reporte sigue saliendo.
        set_phase("descargando población del panel (WDI) para el control por tamaño")
        poblacion = _poblacion_del_panel(list(IRC_PANEL))
        set_phase("calculando correlación IRC vs mortalidad climática")
        report = build_esg_backtest(irc, mortality, poblacion=poblacion)
        sellar(report, "esg_climate", db)
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
        triggers=["esg-backtest"],  # IRC nuevo → re-validar contra la mortalidad realizada
    ))
    register_operation(Operation(
        "esg-backtest", "Backtest del IRC climático",
        "Valida el IRC contra la mortalidad real por desastres climáticos (OWID/"
        "EM-DAT): correlación de Spearman (con IC bootstrap) y monotonía por banda. "
        "Validación direccional preliminar.",
        # Trimestral y no anual: la cascada de `esg-sync` cubre el cambio del IRC, pero el
        # otro insumo —la mortalidad OWID/EM-DAT— se descarga en cada corrida y se actualiza
        # sin avisar. Con la cadencia anual, la próxima corrida caía en junio de 2027.
        _run_esg_backtest, default_interval_hours=2160,
    ))
    registrar_motor(MotorValidacion(
        eje="esg_climate", operacion="esg-backtest", clave=ESG_BACKTEST_KEY,
        partes=huella_backtest, disparado_por=("esg-sync",),
        control_de_tamano=ControlDeTamano(
            clave="control_solo_tamano",
            nota="población del país (`SP.POP.TOTL`), que es el DEFLACTOR del desenlace: la "
                 "mortalidad ya viene por 100.000 habitantes. Se mide con Spearman porque el "
                 "motor es de correlación, no de clasificación"),
        insumo_no_cubierto=("mortalidad por desastres climáticos (OWID/EM-DAT), "
                            "descargada en cada corrida y no persistida",),
    ))


register()
