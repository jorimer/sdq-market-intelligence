"""Social-dev console operations — registers one-social-sync.

Registers the ONE social sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI (Gate F).
"""
import time
from typing import Dict

from modules.social_dev import digepres_sync
from modules.social_dev.digepres_sync import run_digepres_salud
from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

#: Cuánto esperamos al worker antes de soltar la mirada. La corrida completa son
#: trece documentos y ~20 minutos; el margen es holgado porque abandonar temprano no
#: cancela nada, solo deja de contar la verdad.
_ESPERA_MAXIMA_SEG = 60 * 60
_LATIDO_SEG = 5.0
from shared.validation.frescura import MotorValidacion, registrar_motor
from shared.validation.control_tamano import ControlDeTamano

IDM_VALIDITY_KEY = "idm_convergent_validity"


def huella_convergent(db) -> Dict:
    """Estado del insumo de la validez convergente: el IDM persistido y la referencia PNUD.

    La referencia (IDHr) vive en código, no en la base, así que entra a la huella por su
    contenido: si alguien corrige un valor del PNUD, el reporte queda obsoleto igual que si
    hubiera cambiado el índice.
    """
    from sqlalchemy import func

    from modules.social_dev.models.models import DevelopmentScore
    from modules.social_dev.validation.idhr import IDHR

    r = (db.query(func.count(DevelopmentScore.id), func.max(DevelopmentScore.period),
                  func.sum(DevelopmentScore.development_score)).one())
    return {"scores_n": r[0], "scores_hasta": r[1], "scores_suma": r[2],
            "referencia_idhr": sorted(IDHR.items())}


def _run_one_social_sync(params, user_id, set_phase) -> Dict:
    from modules.social_dev.social_sync import one_social_sync
    db = SessionLocal()
    try:
        return one_social_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_idm_snapshot(params, user_id, set_phase) -> Dict:
    from modules.social_dev.service import backfill_idm_scores
    db = SessionLocal()
    try:
        return backfill_idm_scores(db, set_phase=set_phase)
    finally:
        db.close()


def _run_one_education_extract(params, user_id, set_phase) -> Dict:
    """AI-native extraction of by-region education (literacy + schooling years)
    from the full ENHOGAR report → ``sd_indicators``. Needs a prod ANTHROPIC key."""
    from modules.social_dev.education_extract import one_education_sync
    db = SessionLocal()
    try:
        return one_education_sync(db, set_phase=set_phase)
    finally:
        db.close()


def _run_one_publications_sync(params, user_id, set_phase) -> Dict:
    """Ingest the ONE studies (Censo/ENHOGAR/Pobreza/Vitales/Anuario) as
    publications with an AI digest (the BCRD-publications pattern, for ONE)."""
    from shared.publications import catalog as pub_catalog
    from shared.publications import service as pub_service
    db = SessionLocal()
    try:
        keys = pub_catalog.report_keys("ONE")
        results = []
        for i, key in enumerate(keys, 1):
            set_phase(f"ingiriendo {key} ({i}/{len(keys)})")
            row = pub_service.ingest_report(db, key, force=bool((params or {}).get("force")))
            results.append({"report_key": key, "status": row.status if row else "unavailable",
                            "period": row.period if row else None})
        ok = sum(1 for r in results if r["status"] == "ok")
        return {"ingested_ok": ok, "total": len(keys), "results": results, "errors": []}
    finally:
        db.close()


def _run_idm_convergent_validity(params, user_id, set_phase) -> Dict:
    """Compute the IDM convergent-validity report (regional ranking vs PNUD IDHr)
    and persist it. Deterministic (reads persisted scores + committed reference)."""
    import json

    from modules.social_dev.validation.report import build_convergent_validity
    from shared.settings.models import AppSetting
    from shared.validation.frescura import sellar

    set_phase("validez convergente del IDM vs IDH regional del PNUD")
    db = SessionLocal()
    try:
        rep = build_convergent_validity(db)
        sellar(rep, "social_dev", db)
        row = db.query(AppSetting).filter(AppSetting.key == IDM_VALIDITY_KEY).first()
        payload = json.dumps(rep)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=IDM_VALIDITY_KEY, value=payload, is_secret=False))
        db.commit()
        return {"spearman": rep.get("spearman"), "n_regions": rep.get("n_regions"),
                "spearman_ci": rep.get("spearman_ci")}
    finally:
        db.close()


def _run_digepres_salud(params, user_id, set_phase) -> Dict:  # noqa: ARG001
    """Serie del 2.33, leída en el WORKER y esperada desde acá.

    **Despacha y ESPERA, en vez de despachar y volver.** El console marca «completado»
    apenas el runner devuelve, así que despachar y volver diría que la serie está lista
    cuando el worker recién empezó — y esa mentira dura los veinte minutos que tarda. Este
    hilo no cuesta memoria: los 400 MB de PDF se leen del otro lado, que es todo el punto
    de la mudanza.

    Sin broker corre en este proceso. Es el camino de desarrollo y de los tests; en
    producción es el que mató a la API el 2026-08-24, así que queda declarado en el
    resultado (`via`) en vez de ser indistinguible del bueno.
    """
    from shared.config.settings import settings

    force = bool((params or {}).get("force"))
    if not (settings.USE_CELERY and settings.REDIS_URL):
        set_phase("leyendo en ESTE proceso (sin broker)")
        return {**run_digepres_salud(force=force, progreso=set_phase), "via": "proceso_web"}

    from modules.social_dev.tasks import digepres_salud_funcional_task

    tarea = digepres_salud_funcional_task.delay(force=force)
    set_phase("encolada en el worker")
    espera, visto = 0.0, None
    while espera < _ESPERA_MAXIMA_SEG:
        if tarea.ready():
            break
        info = tarea.info if isinstance(tarea.info, dict) else None
        frase = (info or {}).get("phase")
        if frase and frase != visto:
            set_phase(f"worker: {frase}")
            visto = frase
        time.sleep(_LATIDO_SEG)
        espera += _LATIDO_SEG
    if not tarea.ready():
        # No se cancela: la tarea sigue y persiste año por año. Lo que se declara es que
        # DEJAMOS de mirar, que no es lo mismo que que haya fallado.
        return {"error": f"el worker sigue leyendo después de {_ESPERA_MAXIMA_SEG/60:.0f} "
                         f"minutos; la serie se completa igual y la próxima corrida "
                         f"arranca donde ésta quedó"}
    if tarea.failed():
        return {"error": f"la tarea del worker falló: {tarea.result}"}
    return {**(tarea.result or {}), "via": "worker"}


def _run_tramites(params, user_id, set_phase):
    """Catálogo de trámites del Estado → serie del Registro Único (Ley 167-21, art. 39)."""
    from shared.config.settings import settings

    from modules.social_dev.tramites_sync import run_tramites

    # `force` por defecto: la agenda es mensual y el catálogo es un estado vivo. Si hay dos
    # corridas en el mismo mes, la más reciente es la afirmación más verdadera. Se puede
    # desactivar por parámetro para una corrida manual que no quiera reescribir.
    force = bool((params or {}).get("force", True))
    if not (settings.USE_CELERY and settings.REDIS_URL):
        set_phase("leyendo en ESTE proceso (sin broker)")
        return {**run_tramites(force=force, progreso=set_phase), "via": "proceso_web"}

    from modules.social_dev.tasks import tramites_registro_unico_task

    tarea = tramites_registro_unico_task.delay(force=force)
    set_phase("encolada en el worker")
    return {"via": "worker", "task_id": tarea.id}


def register() -> None:
    register_operation(Operation(
        digepres_sync.OPERACION,
        "Serie de gasto en salud del Gobierno Central (2.33 de la END)",
        "Lee la línea de Salud del cuadro de clasificación funcional de los informes de "
        "DIGEPRES y persiste la serie contra el PIB nominal. Corre en el WORKER: son ~400 "
        "MB de PDF y hasta 980 páginas por documento. Es REANUDABLE — cada año se persiste "
        "apenas se lee, así que un corte no obliga a volver a bajar todo.",
        _run_digepres_salud, default_interval_hours=2160,  # anual: el emisor publica 1 vez
    ))
    register_operation(Operation(
        "one-social-sync", "Sincronizar social (ONE pobreza + WDI salud)",
        "Trae la tasa de pobreza monetaria por las 10 regiones de desarrollo (ONE, "
        "2000-…) y la esperanza de vida / mortalidad infantil nacionales (WDI), y "
        "las persiste para el índice de desarrollo (IDM).",
        _run_one_social_sync, default_interval_hours=2160,  # anual → cadencia larga
    ))
    register_operation(Operation(
        "idm-snapshot", "Backfill del índice de desarrollo (IDM)",
        "Calcula+persiste el IDM de las 10 regiones para TODOS los períodos con dato "
        "real (pobreza ONE + salud WDI + rúbrica declarada), y purga cualquier score "
        "fuera del backfill (sin restos de fixture). Publica social.updated.",
        _run_idm_snapshot, default_interval_hours=2160,
        triggers=["idm-convergent-validity"],  # re-puntuar el IDM → re-validar la convergencia
    ))
    register_operation(Operation(
        "one-education-extract", "Alfabetización por región (extracción IA del ENHOGAR)",
        "Lee el informe COMPLETO del ENHOGAR-2022 (ONE) y extrae con IA la tasa de "
        "alfabetización de las 10 regiones de desarrollo (solo lo que el texto "
        "declara; nunca estima). Sube literacy_rate del IDM de rúbrica a real. "
        "(Escolaridad viene de la serie nacional ONE, no de aquí.) Requiere ANTHROPIC.",
        _run_one_education_extract, default_interval_hours=8760,  # estudio puntual → anual+
    ))
    register_operation(Operation(
        "idm-convergent-validity", "Validación del IDM (validez convergente)",
        "Valida el ranking regional del IDM contra el IDH regional (IDHr) del PNUD "
        "para las mismas 10 regiones: Spearman + IC bootstrap. No es un backtest "
        "temporal (no aplica al IDM); es validez convergente vs una medida "
        "independiente de desarrollo. Recalcula desde los scores persistidos.",
        _run_idm_convergent_validity, default_interval_hours=2160,
    ))
    register_operation(Operation(
        "tramites-registro-unico", "Catálogo de trámites del Estado (Registro Único)",
        "Lee los ~710 trámites del Portal Único de Servicios (gob.do) y persiste tres "
        "cifras del mes: cuántos publica el Estado, cuántos declaran su tiempo de "
        "respuesta y la razón entre las dos. Es la serie que sigue la obligación del "
        "artículo 39 de la Ley 167-21 —publicar los procedimientos en el Registro Único— "
        "y el cumplimiento de la Resolución 142-2024 del MAP, que exige el campo de "
        "tiempo. Al 2026-08: 3 de 710.",
        _run_tramites,
        # MENSUAL (~730 h). Sin `anclaje`: el anclaje alinea con el calendario de
        # publicación de una fuente —un trimestre que cierra y se publica 45 días
        # después—, y este catálogo no tiene calendario. Es un estado continuo, así que
        # la cadencia relativa es la correcta y un ancla trimestral lo desfasaría.
        default_interval_hours=730,
    ))
    register_operation(Operation(
        "one-publications-sync", "Ingerir estudios de la ONE (digest IA)",
        "Descarga los estudios/encuestas de la ONE (Censo 2022, ENHOGAR, Boletín de "
        "Pobreza, Estadísticas Vitales, Anuario Sociodemográfico), extrae el texto y "
        "genera un digest de IA, ruteado a Social/ESG. Patrón de publicaciones BCRD.",
        _run_one_publications_sync, default_interval_hours=2160,
    ))

    registrar_motor(MotorValidacion(
        eje="social_dev", operacion="idm-convergent-validity", clave=IDM_VALIDITY_KEY,
        partes=huella_convergent, disparado_por=("idm-snapshot",),
        control_de_tamano=ControlDeTamano(
            motivo="no_medido", variable="población de la región (Censo 2022, ONE)",
            nota="ÚNICO motor del catálogo que sigue sin control, y el motivo es de DATO, no "
                 "de diseño: la población por región de desarrollo no está conectada. La "
                 "fuente existe (X Censo Nacional 2022) pero `www.one.gob.do` responde 403 "
                 "detrás de Cloudflare, así que entra por instantánea comiteada o no entra. "
                 "Las diez regiones sí se ordenarían por tamaño: el control corresponde"),
    ))


register()
