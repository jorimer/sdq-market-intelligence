"""Construction-intel console operations — MIVHED + BCRD + ONE construction sync."""
import logging
from typing import Dict

from shared.database.session import SessionLocal
from shared.operations import Operation, register_operation

logger = logging.getLogger("sdq.construction_intel.operations")


def _run_construction_sync(params, user_id, set_phase) -> Dict:
    """MIVHED + BCRD + ONE: persiste el ICC anual Y el flujo MENSUAL de licencias.

    Una sola descarga del CSV para las dos lecturas. Pedirlo dos veces pagaría la red dos
    veces por el mismo fichero y, peor, admitiría que el mensual y el anual del mismo informe
    salieran de descargas distintas: si el emisor publica entre una y otra, dejan de cuadrar.

    El feed es BEST-EFFORT respecto del índice: si la lectura mensual falla, el ICC se
    persiste igual. El índice anual es el producto publicado y no puede caerse por una
    sección que todavía es piloto.
    """
    from modules.construction_intel.service import (
        backfill_scores, ingest_observaciones_mensuales)
    from shared.data.mivhed_client import mivhed_client

    set_phase("descargando MIVHED (licencias) + BCRD (PIB) + ONE (valor tasado por tipología)")
    ambas = mivhed_client.licenses_ambas()
    db = SessionLocal()
    try:
        set_phase("calculando ICC por año (coyuntura del sector construcción)")
        out = backfill_scores(db, licenses_by_year=ambas["anual"])
        set_phase("persistiendo el flujo mensual de licencias")
        try:
            out["feed_mensual"] = ingest_observaciones_mensuales(db, ambas["mensual"])
        except Exception as e:  # noqa: BLE001 — el feed no tumba el índice
            db.rollback()
            logger.warning("feed mensual del MIVHED no persistido: %s", e)
            out["feed_mensual"] = {"error": str(e)}
        return out
    finally:
        db.close()


#: Nombre de la sonda. Separada del sync a propósito (mismo patrón que `itu-vigilancia`).
SONDA = "mivhed-vigilancia"


def _run_vigilancia_mivhed(params, user_id, set_phase) -> Dict:
    """¿Publicó el MIVHED una edición nueva? Baja el CSV, compara, y NO ingiere nada.

    **El hueco que cierra.** El sync de construcción corre cada 720 h. Si el MIVHED publica
    al día siguiente de un sync, el informe tardaría hasta un mes en enterarse — y mientras
    tanto la sección declararía un atraso que ya no existe. La sonda corre a diario y cuesta
    una descarga: sin modelo, sin BCRD, sin ONE, sin recalcular el ICC.

    Si la fuente trae un mes más nuevo o una fecha de publicación posterior a la que tenemos,
    dispara el sync completo. Si no, deja constancia de que miró y cuándo: esa fecha es la
    que el informe cita como «nuestra última descarga».

    Nunca levanta. Un fallo al descargar NO se registra como verificación: no poder llegar a
    la fuente no es evidencia de que siga igual, y la fecha de la última lectura buena no se
    pisa con una que no leyó nada.
    """
    from datetime import datetime, timezone

    from modules.construction_intel.service import SECTOR_KEY_OBS, guardar_verificacion
    from shared.data.mivhed_client import mivhed_client, parse_licenses_mensual
    from shared.observations import service as obs
    from shared.operations.service import trigger

    set_phase("descargando el CSV de licencias del MIVHED (sin ingerir)")
    try:
        text, publicado_el = mivhed_client._fetch_csv_con_fecha("licencias-emitidas")
        periodos = parse_licenses_mensual(text).get("periodos") or {}
    except Exception as e:  # noqa: BLE001 — la sonda nunca levanta
        logger.warning("vigilancia MIVHED: no se pudo descargar la fuente: %s", e)
        return {"error": f"no se pudo descargar la fuente: {e}",
                "lectura": "no se pudo leer la fuente: NO es evidencia de que siga igual"}
    if not periodos:
        return {"error": "la descarga no trajo ningún mes legible",
                "lectura": "descarga ilegible: NO es evidencia de que siga igual"}

    en_fuente = max(periodos)
    db = SessionLocal()
    try:
        tenemos = obs.ultimo_periodo(db, sector_key=SECTOR_KEY_OBS)
        publicada_nuestra = obs.ultima_publicacion(db, sector_key=SECTOR_KEY_OBS)
        hay_mes_nuevo = tenemos is None or en_fuente > tenemos
        hay_republicacion = bool(publicado_el and (
            publicada_nuestra is None or publicado_el > publicada_nuestra.isoformat()))
        hay_novedad = hay_mes_nuevo or hay_republicacion
        guardar_verificacion(db, {
            "verificado_el": datetime.now(timezone.utc).isoformat(),
            "ultimo_periodo_en_fuente": en_fuente,
            "publicado_el": publicado_el,
            "hay_novedad": hay_novedad,
        })
    finally:
        db.close()

    disparo = None
    if hay_novedad:
        set_phase("la fuente trae novedad: disparando el sync de construcción")
        disparo = trigger("mivhed-construction-sync", origin="sonda")
    return {
        "ultimo_periodo_en_fuente": en_fuente,
        "ultimo_periodo_nuestro": tenemos,
        "publicado_el": publicado_el,
        "hay_novedad": hay_novedad,
        "sync_disparado": disparo,
        "lectura": ("edición nueva: se disparó el sync" if hay_novedad
                    else f"sin novedad: la fuente sigue en {en_fuente}"),
    }


def register() -> None:
    register_operation(Operation(
        "mivhed-construction-sync", "Sincronizar construcción (MIVHED + BCRD + ONE)",
        "Descarga las licencias de construcción del MIVHED (datos.gob.do), el crecimiento "
        "real del PIB de construcción del BCRD y el valor tasado por tipología de la ONE "
        "(one.gob.do), y persiste el Índice de Construcción (ICC) del último año completo "
        "MÁS el flujo mensual de licencias. Dato público real (permisos líder + producción "
        "efectiva + valor tasado autoritativo).",
        # 720 h y no 2160: el ICC sigue siendo anual, pero el feed de licencias es MENSUAL y
        # una cadencia anual lo dejaría hasta once meses sin mirar. Triplica las corridas de
        # sync — red y cómputo, no modelo.
        _run_construction_sync, default_interval_hours=720,
    ))
    register_operation(Operation(
        SONDA, "Vigilar el MIVHED (edición nueva de licencias)",
        "Descarga a diario el CSV de licencias del MIVHED y lo compara con lo que tenemos, sin "
        "ingerir nada. Si trae un mes nuevo o una publicación posterior, dispara el sync de "
        "construcción. Deja registrada la fecha de la verificación, que el informe cita como "
        "«nuestra última descarga». Sin costo de modelo.",
        # 24 h y no la cadencia del sync: es lo que acota a un día el tiempo en que el informe
        # puede declarar un atraso que el emisor ya corrigió.
        _run_vigilancia_mivhed, default_interval_hours=24,
    ))


register()
