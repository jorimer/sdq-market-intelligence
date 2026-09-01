"""Banking-score console operations.

Defines this module's recurring runners and registers them into the shared
operation console (:mod:`shared.operations`). The console framework (status,
history, scheduler) is platform-wide; this module only owns its runners.
"""
import json
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
from shared.operations import Operation, register_operation
from shared.validation.frescura import MotorValidacion, registrar_motor
from shared.validation.control_tamano import ControlDeTamano


def _run_rescore(params, user_id, set_phase) -> Dict:
    from modules.banking_score.scoring.batch import score_all_periods
    db = SessionLocal()
    try:
        return score_all_periods(
            db,
            only_sib=bool(params.get("only_sib", True)),
            created_by=user_id,
            on_progress=lambda i, total, pe: set_phase(f"calculando {pe} ({i}/{total})"),
        )
    finally:
        db.close()


def _run_prune(params, user_id, set_phase) -> Dict:
    from modules.banking_score.sib_sync import prune_future_periods, prune_partial_latest_quarter
    db = SessionLocal()
    try:
        set_phase("podando trimestres futuros")
        future = prune_future_periods(db)
        set_phase("podando trimestre parcial (si lo hay)")
        partial = prune_partial_latest_quarter(db)
        return {"future": future, "partial": partial}
    finally:
        db.close()


def _run_purge_synthetic(params, user_id, set_phase) -> Dict:
    from modules.banking_score.sib_sync import purge_synthetic_data
    db = SessionLocal()
    try:
        set_phase("purgando datos sintéticos (source=manual) y ratings huérfanos")
        return purge_synthetic_data(db)
    finally:
        db.close()


def _run_recompute(params, user_id, set_phase) -> Dict:
    period = params.get("period")
    if not period:
        raise ValueError("Falta el período (YYYY-MM) para recomputar carteras.")
    from modules.banking_score.sib_sync import recompute_carteras_metrics

    def _ws(_db, **updates):  # adapter: route phase → op status
        ph = updates.get("phase")
        if ph:
            set_phase(ph)

    return recompute_carteras_metrics(period, write_status=_ws)


BACKTEST_REPORT_KEY = "backtest_report"


def huella_backtest(db) -> Dict:
    """Estado del insumo del backtest: los ratings que puntúa y los financieros que juzga.

    La SUMA de los scores es la parte que importa. La recalibración del 2026-08-07 no agregó
    una sola observación —1.693 filas y 301 eventos antes y después— y aun así dio vuelta el
    Gini de 0,44 a 0,16: una huella de conteos y períodos la habría declarado "sin cambios"
    y el reporte viejo habría seguido pasando por vigente.
    """
    from sqlalchemy import func

    from modules.banking_score.models.models import BankingData, ModelType, RatingResult

    r = (db.query(func.count(RatingResult.id), func.max(RatingResult.period_end),
                  func.sum(RatingResult.overall_score))
         .filter(RatingResult.model_type == ModelType.deterministic).one())
    d = (db.query(func.count(BankingData.id), func.max(BankingData.period_end),
                  func.sum(BankingData.morosidad_pct), func.sum(BankingData.solvencia_pct),
                  func.sum(BankingData.utilidad_neta)).one())
    return {
        "ratings_n": r[0], "ratings_hasta": r[1], "ratings_suma_score": r[2],
        "financials_n": d[0], "financials_hasta": d[1],
        "financials_suma_morosidad": d[2], "financials_suma_solvencia": d[3],
        "financials_suma_utilidad": d[4],
    }


def _run_backtest(params, user_id, set_phase) -> Dict:
    """Recompute the Eje-1 backtest and persist the report (AppSetting)."""
    from modules.banking_score.validation.report import build_backtest_report
    from shared.validation.frescura import sellar
    db = SessionLocal()
    try:
        set_phase("derivando desenlaces y métricas de discriminación")
        rep = build_backtest_report(db)
        sellar(rep, "banking_score", db)
        row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_REPORT_KEY).first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=BACKTEST_REPORT_KEY, value=payload, is_secret=False))
        db.commit()
        return {"gini": rep.get("gini"), "n_observations": rep.get("n_observations"),
                "n_events": rep.get("n_events"), "monotonic": rep.get("monotonic")}
    finally:
        db.close()


def _run_diagnostico_recalibracion(params, user_id, set_phase) -> Dict:
    """Compara el poder discriminante del score vigente contra el previo a `02fcdd2`.

    Corre donde está el dato —producción— porque la pregunta es sobre el panel real de
    1.693 observaciones, no sobre el de desarrollo. No persiste nada: es un diagnóstico.
    """
    from modules.banking_score.validation.recalibracion import comparar_recalibracion
    db = SessionLocal()
    try:
        set_phase("reconstruyendo el score previo sobre el mismo panel y los mismos desenlaces")
        return comparar_recalibracion(db)
    finally:
        db.close()


def _run_diagnostico_composicion(params, user_id, set_phase) -> Dict:
    """¿`solidez` ordena al revés, o el panel mezcla poblaciones que no se comparan?

    Repite la cuenta de pares del Gini contando SOLO los pares que comparten estrato —tipo
    de entidad y tramo de tamaño— y compara con el agregado. Corre donde está el dato
    —producción— porque la pregunta es sobre el panel real. No persiste nada.
    """
    from modules.banking_score.validation.composicion import diagnosticar_composicion
    dimension = (params or {}).get("dimension") or "solidez"
    db = SessionLocal()
    try:
        set_phase(f"midiendo `{dimension}` dentro de cada tipo de entidad y tramo de tamaño")
        return diagnosticar_composicion(db, dimension=dimension)
    finally:
        db.close()


def _run_materialidad(params, user_id, set_phase) -> Dict:
    """Distribución del activo total por entidad cambiaria, para CALIBRAR el piso.

    La propuesta de 2026-06-08 acotó el alcance de cambiarias a los agentes con balance
    material y dejó el umbral «pendiente de calibración». Esto produce la evidencia con la que
    se fija, contra el panel real. No filtra nada todavía: solo mide.
    """
    from modules.banking_score.scoring.materialidad import perfil_de_materialidad
    tipo = (params or {}).get("tipo") or "cambiaria"
    db = SessionLocal()
    try:
        set_phase(f"midiendo la distribución de activos de las entidades `{tipo}`")
        return perfil_de_materialidad(db, tipo=tipo)
    finally:
        db.close()


def _run_sib_historical_load(params, user_id, set_phase) -> Dict:
    """Carga el ledger histórico de la SB (Cronología SB, 1947→) y deriva los financials.

    Descarga los 7 CSV públicos, los carga a ``sib_historical_ledger`` (idempotente,
    replace por archivo) y reconstruye ``sib_historical_financials`` vía el crosswalk.
    Corre server-side (alcanza la DB interna, descarga en el servidor). Bajo demanda: el
    snapshot de la SB se actualiza esporádicamente; re-correr re-descarga ~518 MB.
    """
    from modules.banking_score.external import sib_historical_client as hist
    from modules.banking_score import sib_historical_crosswalk as xw
    db = SessionLocal()
    try:
        loaded: Dict[str, int] = {}
        n = len(hist.FILES)
        for i, rec in enumerate(hist.FILES, 1):
            name = hist.source_file_name(rec)
            set_phase(f"descargando y cargando {name} ({i}/{n})")
            try:
                loaded[name] = hist.load_file(db, rec)
            except Exception as e:  # noqa: BLE001 — un archivo no debe abortar el resto
                loaded[name] = -1
                set_phase(f"{name} falló: {e}")
        total = sum(v for v in loaded.values() if v and v > 0)
        set_phase(f"derivando financials por entidad ({total:,} filas en el ledger)")
        derived = xw.derive_all(db)
        return {"ledger_rows": total, "derived_rows": derived, "files": loaded}
    finally:
        db.close()


def _run_perfil_sdq(params, user_id, set_phase) -> Dict:
    """Recomputa Perfil SDQ sobre TODO el histórico, sin re-escorear indicadores.

    Distinto de `rescore`: parte de los sub-componentes ya persistidos y solo reagrega, así
    que es rápido y —lo importante— **no genera acciones de rating**. Recalcular el histórico
    entero con `rescore` produciría movimientos de tier entre períodos que no ocurrieron.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.perfil_backfill import backfill_perfil_sdq

    db = SessionLocal()
    try:
        return backfill_perfil_sdq(db, set_phase=set_phase)
    finally:
        db.close()


def _run_reetiquetar_acciones(params, user_id, set_phase) -> Dict:
    """Re-etiqueta el histórico de acciones a Perfil SDQ (spec §9, decisión del dueño).

    No re-escorea: deriva las transiciones por eje de las bandas ya persistidas. Idempotente.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.acciones_por_eje import reetiquetar

    db = SessionLocal()
    try:
        return reetiquetar(db, set_phase=set_phase)
    finally:
        db.close()


def _run_dedup_acciones(params, user_id, set_phase) -> Dict:
    """Deduplica `rating_actions`. Por defecto SIMULA — hay que pasar `ejecutar: true`.

    Un borrado en producción se mira antes de correrlo, así que el valor por defecto cuenta
    y no toca nada.
    """
    from shared.database.session import SessionLocal
    from modules.banking_score.scoring.dedup_acciones import deduplicar

    db = SessionLocal()
    try:
        return deduplicar(db, set_phase=set_phase,
                          ejecutar=bool((params or {}).get("ejecutar")))
    finally:
        db.close()


def cortes_sin_desglose_sectorial(db) -> list:
    """Trimestres con datos bancarios cuyo libro de crédito NO está abierto por sector.

    Es la brecha entre lo que sabemos de cada entidad y lo que sabemos de su cartera. Se
    computa comparando los dos conjuntos, nunca se lleva una lista a mano: un corte nuevo
    aparece solo, y uno que se completó desaparece solo.
    """
    from modules.banking_score.models.models import BankingData
    from shared.reference.cartera_sectorial import CarteraSectorial
    con_datos = {r[0] for r in db.query(BankingData.period_end).distinct()}
    con_desglose = {r[0] for r in db.query(CarteraSectorial.period_end).distinct()}
    return sorted(con_datos - con_desglose, reverse=True)


def _run_sectorial_al_dia(params, user_id, set_phase) -> Dict:
    """Llena el desglose sectorial de los trimestres que aún no lo tienen, DE A UNO.

    Por qué de a uno y no un backfill completo. Un deploy de Railway reinicia el worker y
    mata la operación en vuelo: el 2026-08-29 un backfill de 2h30 murió en el trimestre 14
    de 22 y no dejó nada. Procesar un trimestre por corrida hace que una interrupción cueste
    ocho minutos, y que la siguiente corrida retome donde quedó sin repetir trabajo — la
    brecha se recomputa cada vez contra la base, no contra una lista guardada.

    Por eso también esta operación SÍ puede tener cadencia, mientras que el backfill completo
    no debería: es corta, idempotente y reanudable.
    """
    from modules.banking_score.sib_sync import recompute_carteras_metrics
    cuantos = int(params.get("cortes") or 1)
    db = SessionLocal()
    try:
        faltan = cortes_sin_desglose_sectorial(db)
    finally:
        db.close()
    if not faltan:
        return {"faltaban": 0, "procesados": [], "nota": "todos los trimestres tienen desglose"}

    def _ws(_db, **updates):
        if updates.get("phase"):
            set_phase(updates["phase"])

    hechos = []
    for pe in faltan[:cuantos]:
        periodo = f"{pe.year}-{pe.month:02d}"
        set_phase(f"desglose sectorial de {periodo}")
        r = recompute_carteras_metrics(periodo, write_status=_ws)
        # Un corte puede no tener cubo publicado todavía: se REPORTA, no se reintenta en
        # bucle ni se marca como hecho.
        hechos.append({"corte": periodo, "filas": r.get("rows_updated", 0),
                       "sin_cubo": not r.get("rows_updated")})
    return {"faltaban": len(faltan), "procesados": hechos,
            "quedan": max(0, len(faltan) - len(hechos))}


def _run_sib_sync_liviano(params, user_id, set_phase) -> Dict:
    """Re-ingesta desde la SIB SIN el cubo de carteras. Es la mitad rápida del sync.

    Por qué existe y por qué el backfill completo NO se agenda. El sync entero tarda unas
    dos horas y media, casi todas en transmitir el cubo de créditos; un deploy reinicia el
    worker y lo mata a mitad —pasó el 2026-08-29 y no dejó nada—. Como
    `seed_default_schedules` activa sola toda operación recurrente en el próximo despliegue,
    agendar el completo garantiza repetir ese choque.

    La partición es limpia: esto trae balance, resultados, indicadores y solvencia —lo que
    estuvo DOS MESES sin actualizarse, y por lo que un trimestre entero ya publicado no
    estaba en la plataforma— y `cartera-sectorial-al-dia` trae el cubo de a un trimestre.
    Entre las dos cubren todo sin que ninguna corra horas.
    """
    from modules.banking_score.sib_sync import run_backfill
    set_phase("re-ingesta SIB sin el cubo de carteras")
    return run_backfill(force=True, skip_carteras=True)


def register() -> None:
    """Register banking-score operations into the shared console (idempotent)."""
    register_operation(Operation(
        "perfil-sdq-backfill", "Recomputar Perfil SDQ (histórico)",
        "Calcula Ejecución y Resiliencia para todos los períodos desde los sub-componentes "
        "ya guardados. No re-escorea indicadores ni genera acciones de rating.",
        _run_perfil_sdq, default_interval_hours=0,
        # Reescribe `banda_resiliencia`, que es el eje de la curva de distress por banda:
        # sin re-validar, el reporte publica una curva de bandas que ya no existen.
        triggers=["backtest"],
    ))
    register_operation(Operation(
        "dedup-acciones", "Deduplicar acciones de rating",
        "Deja UNA acción por entidad y período. Por defecto SIMULA: devuelve el conteo sin "
        "borrar. Para ejecutar hay que pasar params {\"ejecutar\": true}.",
        _run_dedup_acciones, default_interval_hours=0,
    ))
    register_operation(Operation(
        "reetiquetar-acciones", "Re-etiquetar acciones a Perfil SDQ (histórico)",
        "Desdobla cada acción de rating en sus dos transiciones de eje, leyéndolas de las "
        "bandas ya persistidas. NO re-escorea ni genera acciones nuevas.",
        _run_reetiquetar_acciones, default_interval_hours=0,
    ))
    register_operation(Operation(
        "rescore", "Recalcular ratings",
        "Recalcula los ratings desde los datos existentes, sin descargar del SIB.",
        _run_rescore, default_interval_hours=168,
        # Re-puntuar → re-validar. Es la cascada que faltaba: la recalibración del 7-ago
        # cambió el score y el backtest tenía su próxima corrida el 26-ago, así que
        # producción sirvió 19 días un Gini calculado con el score anterior.
        # Y → barrer alertas: el reloj del barrido es su respaldo, no su disparador.
        triggers=["backtest", "alerts-sweep"],
    ))
    register_operation(Operation(
        "prune-future", "Eliminar trimestres futuros",
        "Borra datos y ratings de trimestres aún no cerrados (period_end > hoy).",
        _run_prune, default_interval_hours=168,
    ))
    register_operation(Operation(
        "purge-synthetic", "Purgar datos sintéticos (seed)",
        "Borra los datos sembrados sintéticos (source=manual) y los ratings/acciones "
        "que queden huérfanos. El catálogo de entidades y todo dato real "
        "(SIB/SIMBAD/CSV) quedan intactos. Sella el seed: la app solo puntúa dato real. "
        "Correr cuando: quieras sellar el paso de datos de siembra a solo dato real (una vez).",
        _run_purge_synthetic, default_interval_hours=0,
    ))
    register_operation(Operation(
        "recompute-carteras", "Recomputar carteras",
        "Re-descarga las carteras de crédito de un trimestre y actualiza concentración/mora. "
        "Correr cuando: haya que recomputar la cartera de un trimestre puntual (indicá el período).",
        _run_recompute, default_interval_hours=0, needs_params=["period"],
    ))
    register_operation(Operation(
        "backtest", "Backtest del rating",
        "Recalcula la validación de discriminación del rating (Gini + curva de distress por tier).",
        _run_backtest, default_interval_hours=720,
    ))
    register_operation(Operation(
        "sib-historical-load", "Cargar histórico SIB (1947→)",
        "Descarga los CSV históricos de la SB (Cronología SB) y carga el ledger crudo "
        "por-entidad mensual (balance 1947→, resultados 1996→), luego deriva los financials. "
        "Bajo demanda (~518 MB): correr cuando la SB publique un snapshot nuevo.",
        _run_sib_historical_load, default_interval_hours=0,
    ))
    register_operation(Operation(
        "banca-diagnostico-recalibracion", "Diagnóstico: recalibración vs discriminación",
        "Rehace el backtest cambiando UNA sola cosa —el score— para responder si la "
        "recalibración de solidez del 7-ago degradó la discriminación o si el Gini de 0,44 "
        "medía otra cosa. Mismo panel, mismos desenlaces; el score previo se reconstruye con "
        "las curvas de `02fcdd2^`. Reporta además el Gini de cada dimensión por separado. No "
        "persiste nada. On-demand. Correr cuando: haya que defender o revisar la credencial "
        "de discriminación del rating.",
        _run_diagnostico_recalibracion, default_interval_hours=0,
    ))
    register_operation(Operation(
        "banca-diagnostico-composicion", "Diagnóstico: ¿la inversión de solidez es del "
        "indicador o del panel?",
        "Mide una dimensión del score (por defecto `solidez`, la de 40 % de peso y Gini "
        "−0,19) contando SOLO los pares comparables: dentro del mismo tipo de entidad y del "
        "mismo tramo de tamaño. Si la inversión desaparece al estratificar, la produce "
        "mezclar poblaciones (las cambiarias están sobrecapitalizadas por diseño) y el "
        "arreglo NO es la curva del indicador. Devuelve además el Gini de cada indicador de "
        "la dimensión. No persiste nada. On-demand. Correr cuando: haya que decidir dónde se "
        "toca el score. Parámetro opcional: `dimension`.",
        _run_diagnostico_composicion, default_interval_hours=0,
    ))
    register_operation(Operation(
        "banca-materialidad", "Diagnóstico: ¿qué entidades sostienen una calificación?",
        "Mide la distribución del activo total por entidad de un tipo (por defecto "
        "`cambiaria`) y muestra dónde la escalera de tamaños tiene un escalón real. Existe "
        "para CALIBRAR con evidencia el umbral de materialidad que "
        "`docs/PROPUESTA_CAMBIARIAS_FIDUCIARIAS.md` §0 recomendó y dejó pendiente. No filtra "
        "nada: solo mide. On-demand. Parámetro opcional: `tipo`.",
        _run_materialidad, default_interval_hours=0,
    ))
    register_operation(Operation(
        "sib-sync-liviano", "Sincronizar con la SIB (sin el cubo de carteras)",
        "Re-ingesta balance, resultados, indicadores y solvencia desde la SIB. NO baja el "
        "cubo de créditos —de eso se encarga `cartera-sectorial-al-dia`, de a un trimestre—, "
        "y por eso es corta y se puede agendar sin que un deploy la parta a la mitad. "
        "Existe porque la banca era el ÚNICO eje sin cadencia: se descubrió con dos meses de "
        "atraso y un trimestre publicado que nadie había traído.",
        _run_sib_sync_liviano, default_interval_hours=168,
        # Re-ingerir → re-puntuar → re-validar. Misma cascada que `rescore`: sin ella, un
        # dato nuevo convive con un backtest calculado sobre el anterior.
        triggers=["backtest", "alerts-sweep"],
    ))
    register_operation(Operation(
        "cartera-sectorial-al-dia", "Completar el desglose sectorial pendiente",
        "Busca los trimestres con datos bancarios cuyo libro de crédito todavía no está "
        "abierto por sector y provincia, y llena UNO por corrida. La brecha se recomputa "
        "contra la base en cada pasada, así que un corte nuevo entra solo y una "
        "interrupción cuesta un trimestre, no la serie entera. Parámetro opcional: "
        "`cortes` (cuántos por corrida, por defecto 1).",
        _run_sectorial_al_dia, default_interval_hours=168,
    ))
    registrar_motor(MotorValidacion(
        eje="banking_score", operacion="backtest", clave=BACKTEST_REPORT_KEY,
        partes=huella_backtest, disparado_por=("rescore", "perfil-sdq-backfill"),
        # El panel va de un agente de cambio de RD$22 MM a un banco múltiple de RD$30.890 MM.
        # Medido: el activo total SOLO ordena el desenlace con +0,413, mejor que el score.
        control_de_tamano=ControlDeTamano(
            clave="control_solo_tamano",
            nota="activo total de la entidad al corte, misma convención que el score"),
    ))


register()
