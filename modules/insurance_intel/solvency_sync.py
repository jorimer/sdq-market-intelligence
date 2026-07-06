"""SIS Índices de Solvencia y Liquidez ingest → per-insurer regulatory indices.

Ingests the OFFICIAL regulatory solvency and liquidity indices (Ley 146-02, Art. 164)
that the Superintendencia de Seguros publishes per insurer, and attaches them to the
existing aseguradora roster (matched by a normalized brand key, robust to the audited
sheet-name truncation). Also upgrades entity names to the official published names. The
ISF then scores solvency/liquidity on these regulatory indices instead of proxies.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from shared.data.sis_solvency_client import SISSolvencyClient, brand_key
from modules.insurance_intel.external.audited_excel_extractor import slugify_insurer
from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

logger = logging.getLogger("sdq.insurance_intel.solvency_sync")


def _match_slug(key: str, existing: Dict[str, str]) -> Optional[str]:
    """Match a solvency brand key to an existing entity slug. exact → prefix (either
    direction, ≥5 chars) → unique first-token. None if no confident match."""
    if key in existing:
        return existing[key]
    for ek, slug in existing.items():
        short, long = sorted((key, ek), key=len)
        if len(short) >= 5 and long.startswith(short):
            return slug
    first = key.split("_")[0]
    if len(first) >= 5:
        hits = [slug for ek, slug in existing.items() if ek.split("_")[0] == first]
        if len(hits) == 1:
            return hits[0]
    return None


def solvency_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                  mode: str = "live") -> Dict:
    """Ingest the official solvency/liquidity indices → per-entity series + name upgrade."""
    set_phase = set_phase or (lambda _m: None)
    client = SISSolvencyClient(mode="live" if mode == "live" else "fixture")
    client.check_license()
    lineage = Lineage(source=client.source, license=client.license, fetched_at=date.today())

    set_phase("Índices de Solvencia y Liquidez (SIS · Art. 164)")
    used = client.mode
    try:
        records = client.fetch()
    except Exception as e:  # noqa: BLE001 — live failure → committed fixture floor
        logger.warning("[SIS-solvencia] ingesta live falló (%s); uso fixture citado", e)
        client = SISSolvencyClient(mode="fixture")
        records = client.fetch()
        used = "fixture"

    # Existing aseguradora roster → brand_key → slug (for matching).
    ents = {e.slug: e for e in db.query(InsuranceEntity)
            .filter(InsuranceEntity.entity_type == "aseguradora").all()}
    by_key = {brand_key(e.name): e.slug for e in ents.values()}

    matched = created = rows = 0
    seen_new: Dict[str, str] = {}
    for r in records:
        official = r.dimension  # the official company name
        key = brand_key(official)
        slug = _match_slug(key, by_key) or seen_new.get(key)
        if slug is None:
            slug = slugify_insurer(official)
            db.add(InsuranceEntity(slug=slug, name=official, entity_type="aseguradora",
                                   is_active=True))
            ents[slug] = None
            seen_new[key] = slug
            created += 1
        else:
            matched += 1
            ent = ents.get(slug)
            if ent is not None and official and len(official) > len(ent.name or ""):
                ent.name = official  # upgrade to the official (untruncated) name

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
        row.frequency = "quarterly"
        row.source = lineage.source
        row.license = lineage.license
        row.published_at = lineage.fetched_at
        rows += 1

    db.flush()
    set_phase("Recalculando ISF con solvencia/liquidez regulatorias")
    from modules.insurance_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)
    db.commit()
    set_phase("Completado")
    # matched counts unique (series come in pairs solvencia+liquidez)
    return {"records": len(records), "entities_matched": matched // 2,
            "entities_created": created, "series_rows": rows,
            "ratings_written": ratings["ratings_written"], "source": client.source, "mode": used}
