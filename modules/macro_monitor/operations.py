"""Macro-monitor console operations — registers the fiscal pulse sync.

Persists the fiscal dimension of Eje 2 (Hacienda Estado de Operaciones + DGII
recaudación) into MacroSeries, triggerable/monitorable/schedulable from the shared
operation console (Gate F).
"""
import logging
from datetime import datetime, timezone
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger(__name__)

# Marcador anti-spam de la alerta de credencial del API del BCRD. Bajo la cadencia diaria
# de ``macro-live-sync`` esto rinde ~un aviso por día mientras el acceso siga caído — que es
# la frecuencia correcta para algo que solo se arregla escribiéndole al BCRD.
_BCRD_AUTH_ALERT_KEY = "alert:bcrd_api_auth"
_BCRD_AUTH_RENOTIFY_HOURS = 20


def _bcrd_auth_alert(db, message: str) -> None:
    """Avisa a los admin que el API del BCRD rechazó la credencial (best-effort).

    El BCRD desactiva la cuenta del API por inactividad y devuelve el rechazo como error de
    aplicación, indistinguible de un token mal escrito. El correo de desactivación llega al
    buzón personal del titular, no a la plataforma: sin este aviso la fuente queda caída y
    nadie se entera hasta que alguien abre el macro.
    """
    from shared.auth.models import User, UserRole
    from shared.settings.models import AppSetting
    from shared.notifications.service import notification_service

    try:
        row = db.query(AppSetting).filter(AppSetting.key == _BCRD_AUTH_ALERT_KEY).first()
        now = datetime.now(timezone.utc)
        if row and row.value:
            try:
                if (now - datetime.fromisoformat(row.value)).total_seconds() < \
                        _BCRD_AUTH_RENOTIFY_HOURS * 3600:
                    return
            except (ValueError, TypeError):
                pass
        admins = (db.query(User)
                  .filter(User.is_active.is_(True),
                          User.role.in_([UserRole.admin, UserRole.super_admin])).all())
        body = (f"El API del BCRD rechazó la credencial: {message}. Las causas conocidas son "
                "(1) la cuenta desactivada por inactividad —el BCRD la desactiva sola y avisa "
                "por correo al titular—, (2) el token vencido o mal copiado, y (3) la IP de "
                "salida fuera de su lista blanca. Reactivar con apibcrd@bancentral.gov.do y "
                "verificar el token en Configuración → BCRD.")
        for u in admins:
            notification_service.create(db, user_id=u.id, type="error",
                                        title="API del BCRD sin acceso", body=body,
                                        action_url="/settings")
        if row:
            row.value = now.isoformat()
            row.is_secret = False
        else:
            db.add(AppSetting(key=_BCRD_AUTH_ALERT_KEY, value=now.isoformat(), is_secret=False))
        db.commit()
    except Exception as e:  # noqa: BLE001 — el aviso jamás debe tapar el error real
        db.rollback()
        logger.warning("no se pudo avisar del rechazo de credencial del BCRD: %s", e)


def _bcrd_auth_alert_clear(db) -> None:
    """El acceso volvió → limpiar el marcador para re-avisar de inmediato si recae."""
    from shared.settings.models import AppSetting
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _BCRD_AUTH_ALERT_KEY).first()
        if row:
            db.delete(row)
            db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("no se pudo limpiar el marcador de alerta del BCRD: %s", e)


def _run_macro_live_sync(params, user_id, set_phase) -> Dict:
    """Consulta el API autenticado del BCRD (MacroVariables: inflación, agregados
    monetarios, sector real, sector externo → ~25 series) y reconstruye el snapshot macro.

    Es la ÚNICA vía por la que la plataforma usa el token del BCRD de forma recurrente: el
    resto de la ingesta macro (planillas canónicas, publicaciones, comunicados, sectores)
    va por el CDN público, sin credencial. De ahí que la cuenta del API pueda morir por
    inactividad sin que se caiga ningún dato — y que haya que sostenerla con uso REAL, no
    con un ping vacío.

    Diaria: el API entrega el ÚLTIMO valor publicado (snapshot, sin profundidad histórica),
    así que consultarlo a diario es lo que da valor —dato fresco entre las cargas mensuales
    de Excel— y de paso mantiene la cuenta viva. Son 4 POST idempotentes (upsert por
    serie·período), no acumulan nada si el BCRD no publicó nada nuevo.
    """
    from shared.data.bcrd_api import BcrdApiError
    from shared.settings.service import get_sector_api_key

    from modules.macro_monitor.service import build_snapshot, ingest_series
    db = SessionLocal()
    try:
        if not get_sector_api_key(db, "bcrd"):
            raise ValueError(
                "Falta el token del BCRD o la fuente está deshabilitada: pegue la clave en "
                "Configuración → BCRD, marque 'Habilitado' y guarde. Sin esto la cuenta del "
                "API se desactiva por inactividad.")
        set_phase("consultando el API del BCRD (4 variables)")
        try:
            touched = ingest_series(db)
        except BcrdApiError as e:
            if e.is_auth:
                _bcrd_auth_alert(db, e.message)
            raise
        _bcrd_auth_alert_clear(db)
        set_phase("reconstruyendo snapshot (momentum + señales)")
        snap = build_snapshot(db)
        return {
            "observaciones": touched,
            "snapshot": {"period": snap.get("period"), "series": snap.get("series_count")},
        }
    finally:
        db.close()


def _run_fiscal_sync(params, user_id, set_phase) -> Dict:
    from modules.macro_monitor.service import fiscal_sync
    db = SessionLocal()
    try:
        return fiscal_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_bcrd_publications_sync(params, user_id, set_phase) -> Dict:
    """Ingiere la última edición de las publicaciones recurrentes del BCRD (Informe de
    Estabilidad Financiera, Economía Dominicana, IPOM) con digest IA. Idempotente:
    omite las ediciones ya ingeridas salvo force=true en params. (Espejo BCRD del
    ``one-publications-sync``.)"""
    from shared.publications import catalog as pub_catalog
    from shared.publications import service as pub_service
    db = SessionLocal()
    try:
        keys = pub_catalog.report_keys("BCRD")
        results = []
        for i, key in enumerate(keys, 1):
            set_phase(f"ingiriendo {key} ({i}/{len(keys)})")
            row = pub_service.ingest_report(db, key, force=bool((params or {}).get("force")))
            results.append({"report_key": key, "status": row.status if row else "unavailable",
                            "period": row.period if row else None})
        ok = sum(1 for r in results if r["status"] == "ok")
        return {"ingested_ok": ok, "total": len(keys), "results": results}
    finally:
        db.close()


def _run_bcrd_comunicados_sync(params, user_id, set_phase) -> Dict:
    """Descubre e ingiere los comunicados de política monetaria (decisiones de TPM) del BCRD,
    con la decisión estructurada + digest IA del racional. Idempotente por artículo (omite
    los ya ok salvo force=true).

    Params: ``limit`` (default 12, recurrente). ``all=true`` hace el backfill de TODA la
    trayectoria histórica (GetArticles) con SOLO dato estructurado, dejando el digest IA para
    los ``digest_limit`` más recientes (default 24) — barato: sin IA para el histórico."""
    from modules.macro_monitor.comunicados import service as com_service
    from modules.macro_monitor.comunicados import source as com_source
    db = SessionLocal()
    try:
        p = params or {}
        if p.get("all"):
            return com_service.ingest_comunicados(
                db, limit=None, digest_limit=int(p.get("digest_limit", 24)),
                force=bool(p.get("force")), list_fn=com_source.list_all_comunicados,
                set_phase=set_phase)
        return com_service.ingest_comunicados(
            db, limit=int(p.get("limit") or 12), force=bool(p.get("force")),
            set_phase=set_phase)
    finally:
        db.close()


def _run_canonical_ingest(params, user_id, set_phase) -> Dict:
    """Re-ingiere el SET CANÓNICO de planillas Excel del BCRD (balanza de pagos, agregados
    monetarios, IPC, PIB, tasas, llegadas, etc. — las ~600 series normalizadas del macro) y
    reconstruye el snapshot para refrescar momentum + señales de alerta temprana.

    Es la fuente que alimenta a la Data API (`/series`, `/scores`, `/signals`) que consume
    PMS. El extractor captura la unidad que el BCRD declara en cada cuadro y de ahí resuelve
    la naturaleza de la serie (flow/stock/rate/index) para que cada consumidor la lea sin
    adivinar. Idempotente: hace upsert por (serie, período), nunca duplica. Pesado (~20
    archivos, algunos vía Claude) → va por la operación, no por endpoint síncrono. Mensual,
    que es la cadencia con que el BCRD publica estos cuadros."""
    from shared.data.bcrd_excel.canonical import PERSISTIBLES_VERIFICADOS
    from modules.macro_monitor.service import build_snapshot, ingest_canonical
    db = SessionLocal()
    try:
        set_phase("ingiriendo el set canónico del BCRD (unidad + naturaleza)")
        # Se LEEN y se reportan los 26 archivos; se ESCRIBEN solo los verificados. La
        # corrida en seco del 2026-09-03 encontró, en cuatro de los otros archivos, 29.427
        # empates (misma serie y período, valores distintos) que el upsert resuelve por
        # orden de lectura y sin dejar marca. El reporte de cobertura se conserva completo
        # porque es con lo que se decide qué habilitar después.
        # `podar=True`: la sincronización se lleva su propio arrastre. El upsert nunca
        # podaba, así que cada renombrado del extractor dejaba el código viejo sirviendo
        # datos que ya nadie produce —365 series en producción, que hubo que limpiar a
        # mano—. Va con cuatro frenos (ver `_podar_lo_que_ya_no_se_escribe`); el que
        # importa acá es el TOPE: si la poda se llevaría más de la mitad de un archivo, no
        # la ejecuta y la reporta en `prune_halted`, porque un renombrado de esa escala es
        # un evento humano y no algo que una tarea mensual decida sola.
        result = ingest_canonical(db, persist=True, podar=True,
                                  alcance=PERSISTIBLES_VERIFICADOS)
        # La puntuación de pronósticos va ENGANCHADA a la ingesta, no en una operación que
        # alguien tenga que acordarse de correr: un proceso así deja de correr justo el
        # trimestre en que el resultado es malo. Cada corrida busca los `pending` cuyo
        # período ya tenga observado y los puntúa.
        set_phase("puntuando pronósticos con observado disponible")
        from modules.macro_monitor.forecasting.ledger import puntuar_pendientes

        try:
            result["forecasts_scored"] = puntuar_pendientes(db)
        except Exception:  # noqa: BLE001 — puntuar nunca puede tumbar la ingesta
            logger.warning("no se pudieron puntuar los pronósticos", exc_info=True)
            db.rollback()
            result["forecasts_scored"] = None
        set_phase("reconstruyendo snapshot (momentum + señales)")
        snap = build_snapshot(db)
        result["snapshot"] = {"period": snap.get("period"),
                              "series": snap.get("series_count"),
                              "signals": [s["signal"] for s in snap.get("signals", [])]}
        return result
    finally:
        db.close()


def _run_tpm_model_train(params, user_id, set_phase) -> Dict:
    """Entrena el modelo de predicción de TPM (regla de Taylor + clasificador XGBoost),
    corre el backtest time-series y persiste modelo + reporte en AppSetting. Además mantiene
    el track record EN VIVO: (1) puntúa el pronóstico pendiente contra las decisiones ya
    conocidas, (2) re-entrena, (3) congela un pronóstico nuevo para la próxima decisión.

    Pesado (≈100 reentrenamientos en el backtest expanding-window) → va por la operación,
    no por endpoint síncrono. Sirve el forecast en /comunicados/forecast."""
    from modules.macro_monitor.tpm_modeling import ledger, service as tpm_service
    db = SessionLocal()
    try:
        set_phase("puntuando pronósticos pendientes vs decisiones reales")
        scored = ledger.score_pending(db)
        result = tpm_service.train_and_persist(db, trained_by=user_id, set_phase=set_phase)
        set_phase("registrando pronóstico en vivo para la próxima decisión")
        snapshot = ledger.snapshot_forecast(db)
        result["ledger"] = {"scored": scored, "snapshot": snapshot}
        return result
    finally:
        db.close()


def register() -> None:
    register_operation(Operation(
        "macro-live-sync", "Sincronizar macro en vivo (API BCRD)",
        "Consulta el API autenticado del BCRD (MacroVariables: inflación, agregados "
        "monetarios, sector real y sector externo → ~25 series) y reconstruye el snapshot. "
        "Es el ÚNICO consumo recurrente del token del BCRD: todo lo demás (planillas "
        "canónicas, publicaciones, comunicados, sectores) baja del CDN público sin "
        "credencial. Diaria — el API sirve el último valor publicado, así que a diario "
        "trae dato fresco entre las cargas mensuales de Excel y sostiene la cuenta, que el "
        "BCRD desactiva por inactividad. Idempotente (upsert por serie·período). Si el "
        "BCRD rechaza la credencial, avisa a los admin y falla en vez de ingerir vacío.",
        _run_macro_live_sync, default_interval_hours=24,
    ))
    register_operation(Operation(
        "macro-canonical-sync", "Re-ingerir set canónico BCRD + snapshot (macro)",
        "Re-ingiere las ~20 planillas Excel canónicas del BCRD (balanza de pagos, agregados "
        "monetarios, IPC, PIB, tasas, llegadas…) que producen las ~600 series normalizadas "
        "del macro, capturando la unidad declarada y resolviendo la naturaleza de cada serie "
        "(flow/stock/rate/index), y reconstruye el snapshot (momentum + señales de alerta "
        "temprana). Es la fuente que alimenta la Data API que consume PMS. Idempotente "
        "(upsert por serie·período). Mensual — la cadencia de publicación del BCRD; la "
        "aparición de datos nuevos la vigila la auditoría de frescura.",
        _run_canonical_ingest, default_interval_hours=720,
    ))
    register_operation(Operation(
        "fiscal-sync", "Sincronizar pulso fiscal (Hacienda + DGII)",
        "Trae las cuentas fiscales del Estado de Operaciones del Ministerio de "
        "Hacienda (ingresos, gastos y déficit/superávit, mensual desde 2000) y la "
        "recaudación efectiva por grupo de impuesto de la DGII, y las persiste como "
        "series fiscales del macro (Eje 2). Mensual.",
        _run_fiscal_sync, default_interval_hours=720,
    ))
    register_operation(Operation(
        "bcrd-publications-sync", "Ingerir publicaciones BCRD (digest IA)",
        "Descarga la última edición de las publicaciones recurrentes del BCRD "
        "(Informe de Estabilidad Financiera, Informe de la Economía Dominicana e "
        "Informe de Política Monetaria), extrae el texto y genera un digest de IA "
        "ruteado a Macro/Banca. Idempotente (omite ediciones ya ingeridas salvo "
        "force=true en params). Mensual. La aparición de una edición nueva la vigila "
        "la auditoría de frescura de datos.",
        _run_bcrd_publications_sync, default_interval_hours=720,
    ))
    register_operation(Operation(
        "bcrd-comunicados-sync", "Ingerir comunicados de política monetaria (TPM, digest IA)",
        "Descubre los comunicados de política monetaria del BCRD (cada decisión de TPM de "
        "la Junta Monetaria, HTML de la Sala de Prensa), deriva la decisión de forma "
        "determinista (sentido + nivel resultante) y genera un digest de IA del racional, "
        "ruteado a Macro/Banca. Idempotente (omite artículos ya ingeridos salvo "
        "force=true). Mensual — es la señal más oportuna del BCRD.",
        _run_bcrd_comunicados_sync, default_interval_hours=720,
        triggers=["tpm-model-train"],  # dato nuevo de decisiones → reentrena el modelo
    ))
    register_operation(Operation(
        "tpm-model-train", "Entrenar modelo de predicción de TPM",
        "Construye el panel POINT-IN-TIME de decisiones de política monetaria + features "
        "macro del BCRD, estima la regla de reacción tipo Taylor (OLS interpretable) y el "
        "clasificador XGBoost (hold/cut/hike, con pesos por clase por el desbalance), corre "
        "el backtest time-series expanding-window (recall por clase vs baseline 'siempre "
        "mantener') y persiste modelo + backtest. Alimenta /comunicados/forecast. Re-entrenar "
        "tras ingerir comunicados o refrescar las series macro. Mensual.",
        _run_tpm_model_train, default_interval_hours=720,
    ))


register()
