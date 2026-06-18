"""Social-dev console operations — registers one-social-sync.

Registers the ONE social sync into the shared operation console
(:mod:`shared.operations`) so it is triggerable / monitorable / schedulable from
the UI (Gate F).
"""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


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
    ))
    register_operation(Operation(
        "one-education-extract", "Educación por región (extracción IA del ENHOGAR)",
        "Lee el informe COMPLETO del ENHOGAR-2022 (ONE) y extrae con IA la tasa de "
        "alfabetización y los años de escolaridad de las 10 regiones de desarrollo "
        "(solo lo que el texto declara; nunca estima). Sube la dimensión educación "
        "del IDM de rúbrica a dato real. Requiere la clave ANTHROPIC (prod).",
        _run_one_education_extract, default_interval_hours=8760,  # estudio puntual → anual+
    ))
    register_operation(Operation(
        "one-publications-sync", "Ingerir estudios de la ONE (digest IA)",
        "Descarga los estudios/encuestas de la ONE (Censo 2022, ENHOGAR, Boletín de "
        "Pobreza, Estadísticas Vitales, Anuario Sociodemográfico), extrae el texto y "
        "genera un digest de IA, ruteado a Social/ESG. Patrón de publicaciones BCRD.",
        _run_one_publications_sync, default_interval_hours=2160,
    ))


register()
