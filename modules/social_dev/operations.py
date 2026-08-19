"""Social-dev console operations — registers one-social-sync.

Registers the ONE social sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI (Gate F).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation
from shared.validation.frescura import MotorValidacion, registrar_motor

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


def register() -> None:
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
        "one-publications-sync", "Ingerir estudios de la ONE (digest IA)",
        "Descarga los estudios/encuestas de la ONE (Censo 2022, ENHOGAR, Boletín de "
        "Pobreza, Estadísticas Vitales, Anuario Sociodemográfico), extrae el texto y "
        "genera un digest de IA, ruteado a Social/ESG. Patrón de publicaciones BCRD.",
        _run_one_publications_sync, default_interval_hours=2160,
    ))

    registrar_motor(MotorValidacion(
        eje="social_dev", operacion="idm-convergent-validity", clave=IDM_VALIDITY_KEY,
        partes=huella_convergent, disparado_por=("idm-snapshot",),
    ))


register()
