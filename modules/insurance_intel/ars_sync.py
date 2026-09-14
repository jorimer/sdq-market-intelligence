"""SISALRIL BDFINAC ingest → per-ARS financial series + ISARS ratings.

Ingests the ARS (health-risk-manager) regulatory financial figures — margen de solvencia,
ingreso/gasto en salud, beneficio neto — live from the SISALRIL download endpoint when
reachable, else the committed fixture, into ``insurance_series`` (entity_type ``ars``),
seeds the ARS roster, and computes the ISARS (Índice de Solidez de ARS). Idempotent.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sisalril_ars_client import (
    SISALRILARSClient,
    ars_categories,
    ars_name,
)
from modules.insurance_intel.models.models import (
    InsuranceEntity,
    InsuranceRating,
    InsuranceSeries,
)
# A nivel de módulo: `Base.metadata` tiene que conocer la tabla al arrancar.
from shared.observations.models import SectorObservation  # noqa: F401

#: Clave del eje en la tabla transversal de observaciones.
SECTOR_KEY_OBS = "insurance"

#: Cuentas de BALANCE de las ARS que se agregan a nivel SISTEMA para el feed mensual, con el
#: sujeto en el código de destino (`ars.sistema.*`, no `patrimonio` suelto). Son saldos al
#: cierre del mes (plan 0 del BDFINAC), así que sumarlos entre ARS es un total del sistema.
#:
#: Los ingresos, gastos y el beneficio NO entran: son acumulados al mes (crecen dentro del año),
#: y su naturaleza está declarada `unknown` en `shared/data/series_nature.py`.
STOCKS_DE_SISTEMA = {
    "ars.patrimonio": "ars.sistema.patrimonio",
    "ars.activo_total": "ars.sistema.activo_total",
    "ars.margen_inversiones": "ars.sistema.margen_inversiones",
    "ars.margen_requerido": "ars.sistema.margen_requerido",
}

logger = logging.getLogger("sdq.insurance_intel.ars_sync")


def _seed_entities(db: Session, ars_ids, cats: Dict[str, int]) -> int:
    """Seed/refresh ARS entities with their OFFICIAL names (SISALRIL Portal Estadístico).
    Also upgrades names already seeded as coded 'ARS 001 (...)' placeholders."""
    existing = {e.slug: e for e in db.query(InsuranceEntity)
                .filter(InsuranceEntity.entity_type == "ars").all()}
    created = 0
    for ars_id in ars_ids:
        slug = f"ars_{ars_id}"
        cat = cats.get(ars_id)
        name = ars_name(ars_id, cat)
        ent = existing.get(slug)
        if ent is None:
            db.add(InsuranceEntity(slug=slug, name=name, entity_type="ars",
                                   entity_code=str(cat) if cat else None, is_active=True))
            created += 1
        else:
            ent.name = name  # upgrade to the official name
            if cat and not ent.entity_code:
                ent.entity_code = str(cat)
    return created


def _upsert_series(db: Session, records, *, lineage: Lineage) -> int:
    touched = 0
    for r in records:
        slug = f"ars_{r.dimension}"
        row = (db.query(InsuranceSeries)
               .filter(InsuranceSeries.series_code == r.series,
                       InsuranceSeries.period == r.period,
                       InsuranceSeries.entity_slug == slug,
                       InsuranceSeries.dimension.is_(None)).first())
        if row is None:
            row = InsuranceSeries(series_code=r.series, period=r.period, entity_slug=slug)
            db.add(row)
        row.value = r.value
        row.unit = r.unit
        row.frequency = "monthly"
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.fetched_at
        touched += 1
    return touched


def _persist_ratings(db: Session) -> int:
    from modules.insurance_intel.scoring.ars_rating import compute_ars
    written = 0
    for r in compute_ars(db):
        row = (db.query(InsuranceRating)
               .filter(InsuranceRating.entity_slug == r["slug"],
                       InsuranceRating.period == (r["period"] or "—")).first())
        if row is None:
            row = InsuranceRating(entity_slug=r["slug"], period=r["period"] or "—")
            db.add(row)
        row.overall_score = r["overall_score"]
        row.band = r["band"]
        row.coverage = r["coverage"]
        row.dimensions = r["dimensions"]
        row.model_version = "ars-0.1"
        written += 1
    return written


def escribir_agregados_de_sistema(db: Session, records, *, source: str,
                                  license: str) -> Dict[str, int]:
    """Los saldos de SISTEMA de las ARS en `sector_observations`, por período. No commitea.

    **Un total del sistema exige a TODAS las ARS.** El universo son las ARS que aparecen en la
    descarga; un período en el que alguna no reporta la cuenta se persiste con `value=None` y se
    cuenta como incompleto. Sumar 17 de 18 publicaría un sistema más chico con el nombre de
    completo, y el delta leería esa ARS ausente como una caída del sector.

    Idempotente: se borran las series de sistema y se reescriben desde el lote.
    `published_at` queda en NULL: el conector no sabe cuándo publicó SISALRIL, solo cuándo
    descargamos.
    """
    from shared.data.series_nature import infer_nature
    from shared.observations import service as obs

    universo = sorted({r.dimension for r in records if r.dimension})
    por_periodo: Dict[tuple, Dict[str, Optional[float]]] = {}
    for r in records:
        destino = STOCKS_DE_SISTEMA.get(r.series)
        if destino is None or not r.dimension:
            continue
        por_periodo.setdefault((destino, r.period), {})[r.dimension] = r.value

    for destino in STOCKS_DE_SISTEMA.values():
        obs.borrar_serie(db, sector_key=SECTOR_KEY_OBS, series_code=destino)

    completos = incompletos = 0
    for (destino, periodo), valores in sorted(por_periodo.items()):
        faltan = [a for a in universo if valores.get(a) is None]
        if faltan:
            valor = None
            incompletos += 1
        else:
            valor = round(sum(float(valores[a]) for a in universo), 2)
            completos += 1
        obs.upsert(db, sector_key=SECTOR_KEY_OBS, series_code=destino, period=periodo,
                   value=valor, unit="RD$", frequency="monthly",
                   nature=infer_nature("RD$", code=destino), source=source,
                   license=license, published_at=None)
    return {"ars_en_el_universo": len(universo), "puntos_completos": completos,
            "puntos_con_ars_faltantes": incompletos}


def ars_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
             mode: str = "live") -> Dict:
    """Ingest ARS financial series (BDFINAC) → roster + series + ISARS ratings."""
    set_phase = set_phase or (lambda _m: None)
    client = SISALRILARSClient(mode="live" if mode == "live" else "fixture")
    client.check_license()
    lineage = Lineage(source=client.source, license=client.license, fetched_at=date.today())

    set_phase("Estados financieros de ARS (SISALRIL · BDFINAC)")
    used = client.mode
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — live failure → committed fixture floor
        logger.warning("[SISALRIL-ARS] ingesta live falló (%s); uso fixture citado", e)
        client = SISALRILARSClient(mode="fixture")
        records = client.fetch()
        used = "fixture"

    ars_ids = sorted({r.dimension for r in records if r.dimension})
    set_phase("Roster de ARS")
    created = _seed_entities(db, ars_ids, ars_categories())
    set_phase("Series por ARS")
    rows = _upsert_series(db, records, lineage=lineage)
    db.flush()

    set_phase("Índice de Solidez de ARS (ISARS)")
    ratings = _persist_ratings(db)
    set_phase("Feed mensual: saldos de sistema de las ARS")
    agregados = escribir_agregados_de_sistema(db, records, source=client.source,
                                              license=client.license)
    db.commit()
    set_phase("Completado")
    return {"ars": len(ars_ids), "entities_created": created, "series_rows": rows,
            "ratings_written": ratings, "agregados_de_sistema": agregados,
            "source": client.source, "mode": used}
