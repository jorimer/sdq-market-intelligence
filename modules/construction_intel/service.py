"""Construction Intel — ICC computation, persistence and events.

Reads MIVHED open data (building-permit activity) via ``mivhed_client`` and the BCRD's
construction-sector real growth via ``shared.data.bcrd_sectors``, computes the construction
index (ICC) for the latest COMPLETE year and persists it. A partial current year (a quarter
of permits, not a full year) is dropped — never annualized.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.construction_intel.events import publish_construction_updated
from modules.construction_intel.models.models import ConstructionScore
from modules.construction_intel.scoring.momentum import compute_construction_index
# El modelo se importa acá, a nivel de módulo, y no dentro de las funciones que lo usan:
# `Base.metadata` tiene que conocer la tabla al ARRANCAR. Una tabla que Alembic ve y la app
# no registra no rompe producción —la migración la crea— pero no existe cuando la base se
# monta desde el metadata, que es como corren los tests y como se arma un informe a mano. Lo
# vigila `shared/tests/test_alembic_ve_todas_las_tablas.py`, y este import es su respuesta.
from shared.observations.models import SectorObservation  # noqa: F401

logger = logging.getLogger("sdq.construction_intel.service")

MODEL_VERSION = "1.0"

#: Clave del eje en el catálogo de productos y en la tabla de observaciones.
SECTOR_KEY_OBS = "construction"

_MONTHS_FULL_YEAR = 12  # un año "completo" del MIVHED tiene los 12 meses


def _bcrd_construction_growth() -> Dict[int, float]:
    """``{year: real_growth_pct}`` del PIB de construcción (BCRD cuentas nacionales)."""
    from shared.data.bcrd_sectors import VAR_GROWTH, bcrd_sectors_client
    out: Dict[int, float] = {}
    for r in bcrd_sectors_client.fetch(series=VAR_GROWTH):
        if getattr(r, "dimension", None) == "construccion" and r.value is not None:
            try:
                out[int(r.period)] = float(r.value)
            except (ValueError, TypeError):
                continue
    return out


def _complete_years(licenses_by_year: Dict[int, Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Solo los años con los 12 meses presentes (descarta un año en curso parcial)."""
    return {y: r for y, r in licenses_by_year.items()
            if r.get("months", 0) >= _MONTHS_FULL_YEAR}


def _fetch_one_typology() -> Optional[Dict[str, Any]]:
    """Detalle por tipología de la ONE (valor tasado + construcciones + licencias + m²) del
    último año disponible, o ``None`` si la ONE no está accesible. Defensivo: la ONE es una
    capa autoritativa COMPLEMENTARIA — si falla, el ICC (sobre MIVHED+BCRD) no se cae."""
    try:
        from shared.data.one_construction import one_construction_client
        return one_construction_client.latest_typology()
    except Exception as e:  # noqa: BLE001
        logger.warning("ONE construcción no disponible (se omite la capa de valor tasado): %s", e)
        return None


def assemble_construction_dataset(
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch MIVHED permits + BCRD construction growth (live) unless provided, and compute
    the ICC for the latest complete year. Raises if there is no complete year. Fully-provided
    inputs (tests) never hit the network.

    En modo live (sin ``licenses_by_year``) también trae la capa autoritativa de la ONE (valor
    tasado por tipología) y la adjunta al índice; los tests inyectan ``one_typology`` si la
    quieren ejercitar (o lo dejan en ``None``)."""
    live = licenses_by_year is None
    if licenses_by_year is None:
        from shared.data.mivhed_client import mivhed_client
        licenses_by_year = mivhed_client.licenses()
    if growth_by_year is None:
        growth_by_year = _bcrd_construction_growth()
    if one_typology is None and live:
        one_typology = _fetch_one_typology()
    complete = _complete_years(licenses_by_year)
    if not complete:
        raise ValueError("MIVHED no devolvió ningún año completo de licencias.")
    period = max(complete)
    index = compute_construction_index(complete, growth_by_year, period=period)
    if one_typology:
        index["one_typology"] = one_typology
    return {"period": str(period), "index": index}


def _write_score(db: Session, period: str, index: Dict[str, Any]) -> ConstructionScore:
    """Upsert (sin commit) la fila ICC de un período. Reusado por compute y backfill."""
    row = db.query(ConstructionScore).filter_by(period=period).first()
    if row is None:
        row = ConstructionScore(period=period)
        db.add(row)
    levels = index["levels"] or {}
    row.icc_score = index["icc_score"]
    row.band = index["band"]
    row.coverage = index["coverage"]
    row.permits = levels.get("permits")
    row.sqm = levels.get("sqm")
    row.investment_dop = levels.get("investment_dop")
    row.prod_growth_3y = levels.get("prod_growth_3y")
    row.breakdown = {"dimensions": index["dimensions"], "production": index["production"],
                     "pipeline": index["pipeline"], "typology": index["typology"],
                     "geography": index["geography"], "levels": levels,
                     "one_typology": index.get("one_typology")}
    row.model_version = MODEL_VERSION
    return row


def compute_and_persist(
    db: Session,
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the ICC for the latest complete year, persist it and publish
    ``construction.updated``. Idempotent per period: re-running replaces the score in place."""
    asm = assemble_construction_dataset(licenses_by_year, growth_by_year, one_typology)
    period, index = asm["period"], asm["index"]

    row = _write_score(db, period, index)
    db.commit()
    db.refresh(row)
    payload = {"period": period, "icc_score": index["icc_score"], "band": index["band"]}
    publish_construction_updated(payload)
    logger.info("ICC %s: score=%s (%s), coverage=%s",
                period, index["icc_score"], index["band"], index["coverage"])
    return {"period": period, "score_id": row.id, **payload, "coverage": index["coverage"],
            "model_version": MODEL_VERSION}


# ── Feed sub-anual: las observaciones mensuales del MIVHED ──────────────────────────
#
# Las series que se persisten. Los códigos son estables y llevan su emisor adelante, porque
# la observación viaja a una tabla TRANSVERSAL donde conviven los ejes: `permisos` a secas
# colisionaría con cualquier otro eje que licencie algo.
SERIE_PERMISOS = "mivhed.licencias.permisos"
SERIE_SQM = "mivhed.licencias.metros_cuadrados"

#: Etiquetas legibles de las series, para el contexto del narrador y el panel.
ETIQUETAS_DEL_FEED = {
    SERIE_PERMISOS: "licencias de construcción emitidas",
    SERIE_SQM: "metros cuadrados licenciados",
}

#: Clave con la que el sensor de fuentes congeladas identifica ESTE feed dentro del eje.
CLAVE_DEL_FEED = "mivhed_mensual"

#: La inversión del MIVHED NO se persiste como observación. Verificado el 2026-07-14: es un
#: costo estándar derivado (el 94 % de las filas es exactamente m² × RD$61.600 y el resto
#: m² × RD$57.200), no un valor declarado ni tasado por permiso. Publicarla como magnitud
#: monetaria independiente serviría los m² dos veces, una de ellas disfrazada de dinero.
_INVERSION_ES_REDUNDANTE_CON_LOS_M2 = True


#: Clave de configuración donde la sonda deja su última verificación EXITOSA. Clave propia y
#: no el `last_result` de la operación: una corrida fallida sobrescribe el resultado, y la
#: fecha de «la última vez que miramos la fuente y la leímos» no puede borrarse porque la
#: siguiente no llegó.
CLAVE_VERIFICACION = "construction.mivhed.ultima_verificacion"


def guardar_verificacion(db: Session, registro: Dict[str, Any]) -> None:
    """Persiste la última verificación exitosa de la fuente del feed. Commitea."""
    import json

    from shared.settings.models import AppSetting

    valor = json.dumps(registro, ensure_ascii=False, default=str)
    row = db.query(AppSetting).filter(AppSetting.key == CLAVE_VERIFICACION).first()
    if row is None:
        db.add(AppSetting(key=CLAVE_VERIFICACION, value=valor, is_secret=False))
    else:
        # `AppSetting` es del estilo `Column` y el checker ve `Column[str]` donde hay un `str`:
        # el mismo ruido que el baseline carga ~1.300 veces, no un error de tipo real.
        row.value = valor  # type: ignore[assignment]
    db.commit()


def leer_verificacion(db: Session) -> Optional[Dict[str, Any]]:
    import json

    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == CLAVE_VERIFICACION).first()
    if row is None or not row.value:
        return None
    try:
        dato = json.loads(str(row.value))
    except (TypeError, ValueError):
        return None
    return dato if isinstance(dato, dict) else None


def ultima_descarga_del_feed(db: Session) -> Optional[date]:
    """La fecha más reciente en que DESCARGAMOS la fuente del feed y la leímos, o ``None``.

    Hay dos descargas que cuentan, y se toma la más nueva: la de la SONDA diaria, que baja el
    CSV para comparar sin ingerir, y la del SYNC, que reescribe las observaciones (su
    `created_at` es la hora de esa ingesta, porque la ingesta borra y reescribe).
    """
    from datetime import datetime

    from sqlalchemy import func

    from shared.observations.models import SectorObservation

    candidatas: List[date] = []
    fila = (db.query(func.max(SectorObservation.created_at))
            .filter(SectorObservation.sector_key == SECTOR_KEY_OBS).first())
    if fila and fila[0]:
        candidatas.append(fila[0].date() if isinstance(fila[0], datetime) else fila[0])
    verif = leer_verificacion(db) or {}
    try:
        if verif.get("verificado_el"):
            candidatas.append(date.fromisoformat(str(verif["verificado_el"])[:10]))
    except ValueError:
        pass
    return max(candidatas) if candidatas else None


def ingest_observaciones_mensuales(db: Session,
                                   mensual: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Persiste el flujo MENSUAL de licencias del MIVHED en la tabla de observaciones.

    No toca el ICC ni ninguna de sus entradas: es un feed que convive con el índice anual,
    no una recalibración suya. El índice sigue leyéndose de ``parse_licenses``.

    Idempotente: borra la serie del eje y la reescribe. El CSV del MIVHED es un archivo
    completo en cada descarga —no un incremento— así que un upsert fila a fila dejaría vivos
    los meses que el emisor haya retirado, y un mes retirado que sobrevive es peor que uno
    que falta: no hay forma de notarlo.
    """
    from shared.data.series_nature import FLOW
    from shared.observations import service as obs

    if mensual is None:
        from shared.data.mivhed_client import mivhed_client
        mensual = mivhed_client.licenses_mensual()

    periodos = (mensual or {}).get("periodos") or {}
    sin_mes = int((mensual or {}).get("sin_mes") or 0)
    if not periodos:
        return {"periodos": 0, "filas": 0, "sin_mes": sin_mes,
                "motivo": "el MIVHED no devolvió ningún mes legible"}

    from datetime import date as _date

    from shared.data.mivhed_client import mivhed_client as _mc
    emisor, licencia = _mc.source, _mc.license
    # CUÁNDO publicó el emisor esta edición. Es lo que permite declarar «la fuente no publica
    # desde tal fecha» computándolo, en vez de escribir la fecha a mano. Una fecha ilegible
    # queda en NULL: se declara que no se sabe.
    publicado_el = None
    try:
        crudo = (mensual or {}).get("publicado_el")
        publicado_el = _date.fromisoformat(str(crudo)[:10]) if crudo else None
    except ValueError:
        publicado_el = None

    for codigo in (SERIE_PERMISOS, SERIE_SQM):
        obs.borrar_serie(db, sector_key=SECTOR_KEY_OBS, series_code=codigo)

    filas = 0
    for periodo, rec in sorted(periodos.items()):
        for codigo, valor, unidad in ((SERIE_PERMISOS, rec.get("permits"), "conteo"),
                                      (SERIE_SQM, rec.get("sqm"), "m2")):
            obs.upsert(db, sector_key=SECTOR_KEY_OBS, series_code=codigo, period=periodo,
                       value=None if valor is None else float(valor), unit=unidad,
                       frequency="monthly", nature=FLOW, source=emisor, license=licencia,
                       published_at=publicado_el)
            filas += 1
        # El microdato por dimensión, que el agregado anual descartaba. Es la diferencia
        # entre «el sector creció» y «tal plaza concentra tal cosa».
        for campo, mapa in (("provincia", rec.get("by_province") or {}),
                            ("tipologia", rec.get("by_typology") or {})):
            for nombre, d in mapa.items():
                obs.upsert(db, sector_key=SECTOR_KEY_OBS, series_code=SERIE_SQM,
                           period=periodo, value=float(d.get("sqm") or 0.0), unit="m2",
                           frequency="monthly", nature=FLOW, source=emisor,
                           license=licencia, published_at=publicado_el,
                           **{campo: nombre[:80]})
                filas += 1
    db.commit()
    logger.info("MIVHED mensual: %d período(s), %d fila(s), %d permiso(s) sin mes legible",
                len(periodos), filas, sin_mes)
    return {"periodos": len(periodos), "filas": filas, "sin_mes": sin_mes,
            "ultimo_periodo": max(periodos),
            "publicado_el": publicado_el.isoformat() if publicado_el else None}


def backfill_scores(
    db: Session,
    licenses_by_year: Optional[Dict[int, Dict[str, Any]]] = None,
    growth_by_year: Optional[Dict[int, float]] = None,
    one_typology: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute & persist the ICC for every COMPLETE, FULL-COVERAGE year.

    Solo se persisten los años con las 4 dimensiones medibles (cobertura plena). El pipeline
    (CAGR de m²) solo acredita su peso desde que hay ≥4 años de MIVHED (desde 2022), así que
    los años previos quedarían sin esa dimensión: persistirlos sería un ÍNDICE INCOMPARABLE
    (una serie 'sin la señal de pipeline' junto a otra 'con ella' lee como un falso colapso —
    la palanca fácil-pero-incorrecta). Mejor un punto honesto hoy; la serie crece sola a
    medida que el MIVHED acumula años. Publica el evento UNA vez (con el último año).
    Idempotente: upsert por período."""
    live = licenses_by_year is None
    if licenses_by_year is None:
        from shared.data.mivhed_client import mivhed_client
        licenses_by_year = mivhed_client.licenses()
    if growth_by_year is None:
        growth_by_year = _bcrd_construction_growth()
    if one_typology is None and live:
        one_typology = _fetch_one_typology()
    complete = _complete_years(licenses_by_year)
    if not complete:
        raise ValueError("MIVHED no devolvió ningún año completo de licencias.")

    persisted: List[str] = []
    last: Optional[Dict[str, Any]] = None
    for y in sorted(complete):
        index = compute_construction_index(complete, growth_by_year, period=y)
        # cobertura plena: las 4 dimensiones medibles (índice comparable año a año)
        if index["icc_score"] is None or (index["coverage"] or 0.0) < 0.999:
            continue
        # La capa ONE (valor tasado por tipología) se adjunta SOLO al año que coincide con el
        # año de la ONE — nunca se estampa un valor tasado de otro año en un período ajeno.
        if one_typology and str(one_typology.get("year")) == str(y):
            index["one_typology"] = one_typology
        _write_score(db, str(y), index)
        persisted.append(str(y))
        last = {"period": str(y), "icc_score": index["icc_score"], "band": index["band"]}
    db.commit()
    if last:
        publish_construction_updated(last)
    logger.info("ICC backfill: %d años persistidos (%s..%s)",
                len(persisted), persisted[0] if persisted else "—",
                persisted[-1] if persisted else "—")
    return {"persisted_periods": persisted, "latest": persisted[-1] if persisted else None,
            "count": len(persisted), "model_version": MODEL_VERSION}


def get_latest(db: Session, period: Optional[str] = None) -> Optional[ConstructionScore]:
    q = db.query(ConstructionScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(ConstructionScore.period.desc()).first()


def get_scores(db: Session) -> List[ConstructionScore]:
    return db.query(ConstructionScore).order_by(ConstructionScore.period.desc()).all()
