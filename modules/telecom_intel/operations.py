"""Telecom-intel console operations — INDOTEL telecom-development sync."""
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation


def _run_itu_telecom_sync(params, user_id, set_phase) -> Dict:
    """Fetch ITU DataHub telecom penetration (live source) and persist the IDT.

    Backfill por año (cobertura plena 3/3): un IDT por cada año comparable de la serie
    ITU, no solo el más reciente — así el selector de períodos ofrece la serie real."""
    from modules.telecom_intel.service import backfill_scores_itu

    set_phase("descargando penetración telecom de RD (ITU DataHub API)")
    db = SessionLocal()
    try:
        set_phase("calculando IDT por año (backfill de cobertura plena)")
        return backfill_scores_itu(db)
    finally:
        db.close()


def _run_indotel_telecom_sync(params, user_id, set_phase) -> Dict:
    """Fetch INDOTEL's frozen 2022-Q1 bulletin and persist the IDT (histórico)."""
    from modules.telecom_intel.service import compute_and_persist

    set_phase("descargando boletín trimestral de indicadores (INDOTEL)")
    db = SessionLocal()
    try:
        set_phase("calculando IDT (desarrollo telecom)")
        return compute_and_persist(db)
    finally:
        db.close()


def _run_vigilancia_indotel(params, user_id, set_phase) -> Dict:
    """¿Volvió INDOTEL a publicar? Si sí, lo propone; si no, deja constancia de que se miró.

    El boletín se congeló en 2022-Q1 y el IDT pasó a ITU. Eso es una DECISIÓN, no una
    brecha — pero una decisión que, sin vigilancia, hay que volver a tomar a mano cada vez
    que alguien pregunta si INDOTEL volvió. La sonda contesta sola y, cuando aparece un
    boletín más nuevo, lo sube al tablero de Inteligencia de Fuentes: el sistema propone y
    el dueño dispone (no se re-cablea la fuente vigente por sorpresa).
    """
    from shared.data.indotel_client import LATEST_PERIOD, descubrir_boletin_mas_reciente
    from shared.source_intel.models import KIND_SOURCE, ORIGIN_CATALOG
    from shared.source_intel.service import create_suggestion

    set_phase("buscando boletines trimestrales publicados por INDOTEL")
    hallazgo = descubrir_boletin_mas_reciente()
    if not hallazgo["hay_mas_nuevo"]:
        return {**hallazgo, "sugerencia": None,
                "lectura": ("sigue congelado en " + LATEST_PERIOD if hallazgo["paginas_ok"]
                            else "no se pudo leer ninguna página oficial: NO es evidencia "
                                 "de que siga congelado")}
    db = SessionLocal()
    try:
        sug = create_suggestion(
            db, kind=KIND_SOURCE, origin=ORIGIN_CATALOG, target_axis="telecom",
            target_gate="g1",
            title=f"INDOTEL volvió a publicar: boletín {hallazgo['periodo']}",
            description=(
                f"La sonda encontró un boletín trimestral más nuevo que el conocido "
                f"({LATEST_PERIOD}): {hallazgo['periodo']} en {hallazgo['url']}. La fuente "
                f"vigente del IDT es ITU DataHub (anual); INDOTEL daría cadencia TRIMESTRAL "
                f"y el detalle por operador que ITU no tiene. Decidir si se re-apunta "
                f"`LATEST_BULLETIN` y con qué fuente se calcula el índice."),
        )
        return {**hallazgo, "sugerencia": sug.get("id"), "lectura": "hay boletín más nuevo"}
    finally:
        db.close()


def register() -> None:
    # Fuente VIGENTE: ITU DataHub (INDOTEL congelado en 2022-Q1). Anual, API abierta.
    register_operation(Operation(
        "itu-telecom-sync", "Sincronizar telecom (ITU DataHub)",
        "Descarga la penetración telecom de RD de la API abierta de ITU DataHub "
        "(móvil, banda ancha móvil/fija, hogares con internet; per-100/%, fresca hasta "
        "2024) y persiste el Índice de Desarrollo Telecom (IDT). Reemplaza a INDOTEL, "
        "cuyo boletín público quedó congelado en 2022-Q1.",
        _run_itu_telecom_sync, default_interval_hours=8760,  # anual
    ))
    # Histórico/on-demand: el boletín INDOTEL (2022-Q1), conservado para trazabilidad.
    register_operation(Operation(
        "indotel-telecom-sync", "Sincronizar telecom (INDOTEL · histórico 2022-Q1)",
        "Descarga el boletín trimestral de INDOTEL (XLSX), congelado en 2022-Q1, y "
        "persiste su IDT. Histórico: la fuente vigente es ITU (itu-telecom-sync). "
        "Correr cuando: necesites recargar el histórico congelado de INDOTEL (rara vez).",
        _run_indotel_telecom_sync, default_interval_hours=0,  # on-demand (histórico)
    ))
    register_operation(Operation(
        "indotel-vigilancia", "Vigilar si INDOTEL volvió a publicar",
        "Sonda las páginas oficiales de estadísticas de INDOTEL y compara el boletín "
        "trimestral más nuevo publicado con el que el conector conoce (2022-Q1). Si "
        "aparece uno posterior, lo propone en el tablero de Inteligencia de Fuentes para "
        "que el dueño decida si se re-apunta la fuente del IDT. No ingiere ni promueve "
        "nada. Convierte «telecom está congelado» de un hecho que hay que recordar en uno "
        "que el sistema vigila. Mensual.",
        _run_vigilancia_indotel, default_interval_hours=720,
    ))


register()
