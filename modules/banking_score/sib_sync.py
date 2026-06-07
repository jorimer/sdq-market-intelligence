"""SIB synchronization: backfill real data + status reporting.

Ported (and slimmed) from the original app's ``sib_sync_scheduler``. The
backfill replaces seed/synthetic ``banking_data`` with real figures pulled from
the SIB API (via :mod:`modules.banking_score.external.sib_data_client`), matching
entities by their official name (the seed ``short`` names align 1:1 with the SIB
entity catalog) and stamping ``source=sib_api``.

Only quarter-end periods are ingested (the platform is quarterly; the model's
PeriodType has no monthly value). Long-running work runs in a background thread;
progress is exposed via :func:`get_sync_status` for the "Sincronización SIB" UI.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from modules.banking_score.external.sib_data_client import (
    SIB_ENTITY_CODES,
    get_sib_data_client,
)
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    DataSource,
    PeriodType,
    RatingResult,
)
from modules.banking_score.seed.banking_seed import BANKING_ENTITIES

logger = logging.getLogger("sdq.banking.sib_sync")

# Official bank name per SIB short name (seed shorts match the SIB catalog 1:1).
_SHORT_TO_NAME = {e["short"]: e["name"] for e in BANKING_ENTITIES}

_sync_status: Dict = {
    "is_running": False,
    "last_sync": None,
    "last_check": None,
    "next_scheduled": None,
    "backfill_done": False,
    "last_sync_result": None,
    "alerts": [],
}
_lock = threading.Lock()


def get_sync_status() -> Dict:
    return dict(_sync_status)


def bank_data_stats(db: Session) -> Dict:
    entities = db.query(func.count(Bank.id)).scalar() or 0
    records = db.query(func.count(BankingData.id)).scalar() or 0
    ratings = db.query(func.count(RatingResult.id)).scalar() or 0
    rng = db.query(func.min(BankingData.period_end), func.max(BankingData.period_end)).first()
    sib_records = (
        db.query(func.count(BankingData.id))
        .filter(BankingData.source == DataSource.sib_api)
        .scalar()
        or 0
    )
    return {
        "entities": entities,
        "records": records,
        "ratings": ratings,
        "sib_records": sib_records,
        "period_start": str(rng[0]) if rng and rng[0] else None,
        "period_end": str(rng[1]) if rng and rng[1] else None,
    }


def needs_backfill(db: Session) -> bool:
    """True when there's data but none of it came from the real SIB API yet."""
    total = db.query(func.count(BankingData.id)).scalar() or 0
    sib = (
        db.query(func.count(BankingData.id))
        .filter(BankingData.source == DataSource.sib_api)
        .scalar()
        or 0
    )
    return total > 0 and sib == 0


def _match_bank(db: Session, short_name: str) -> Optional[Bank]:
    name = _SHORT_TO_NAME.get(short_name)
    if not name:
        return None
    return db.query(Bank).filter(Bank.name == name).first()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_backfill(force: bool = False, period_start: str = "2021-01") -> Dict:
    """Replace synthetic data with real SIB data (quarter-end periods only).

    Synchronous — callers run it in a background thread. Returns a summary and
    updates the module-level sync status.
    """
    with _lock:
        if _sync_status["is_running"]:
            return {"status": "already_running", "message": "Ya hay una sincronización en progreso."}
        _sync_status["is_running"] = True

    try:
        db = SessionLocal()
        try:
            if not force and not needs_backfill(db):
                return {
                    "status": "skipped",
                    "message": "Ya hay datos reales del SIB (source=sib_api). Use force=true para re-ejecutar.",
                }
        finally:
            db.close()

        client = get_sib_data_client(force_new=True)
        if client is None:
            msg = "Clave del SIB no configurada. Configúrela en Configuración → APIs de Benchmarks por Sector."
            _sync_status["alerts"] = (_sync_status["alerts"] + [msg])[-50:]
            return {"status": "error", "message": msg}

        _sync_status["last_check"] = _now()
        conn = client.check_connectivity()
        if not conn.get("reachable"):
            msg = f"No se pudo alcanzar la API del SIB ({conn.get('status_code')}). ¿Proxy configurado?"
            _sync_status["alerts"] = (_sync_status["alerts"] + [msg])[-50:]
            return {"status": "error", "message": msg, "connectivity": conn}

        bulk = client.extract_all_entities_bulk(period_start=period_start)

        created = updated = matched = skipped_period = 0
        errors = []
        db = SessionLocal()
        try:
            for short_name, periods in bulk.items():
                if short_name.startswith("_"):
                    continue
                bank = _match_bank(db, short_name)
                if not bank:
                    errors.append(f"{short_name}: banco no encontrado en la base")
                    continue
                matched += 1
                code = SIB_ENTITY_CODES.get(short_name, {}).get("sib_code")
                if code and not bank.sib_code:
                    bank.sib_code = code

                for rec in periods:
                    rec = dict(rec)
                    pe = rec.pop("period_end")
                    rec.pop("period_type", None)
                    rec.pop("source", None)
                    # Quarterly platform: only ingest quarter-end periods.
                    if pe.month not in (3, 6, 9, 12):
                        skipped_period += 1
                        continue
                    existing = (
                        db.query(BankingData)
                        .filter_by(bank_id=bank.id, period_end=pe)
                        .first()
                    )
                    row = existing or BankingData(bank_id=bank.id, period_end=pe)
                    row.period_type = PeriodType.quarterly
                    row.source = DataSource.sib_api
                    for k, v in rec.items():
                        if v is not None:
                            setattr(row, k, v)
                    if existing:
                        updated += 1
                    else:
                        db.add(row)
                        created += 1
                db.commit()
        finally:
            db.close()

        result = {
            "status": "completed",
            "entities_matched": matched,
            "records_created": created,
            "records_updated": updated,
            "periods_skipped_non_quarterly": skipped_period,
            "unmatched": bulk.get("_unmatched", []),
            "errors": errors[:20],
        }
        _sync_status["last_sync"] = _now()
        _sync_status["backfill_done"] = True
        _sync_status["last_sync_result"] = result
        logger.info("SIB backfill: %s", result)
        return result
    except Exception as e:  # noqa: BLE001 — report any failure into status
        logger.exception("SIB backfill failed")
        _sync_status["alerts"] = (_sync_status["alerts"] + [str(e)[:200]])[-50:]
        return {"status": "error", "message": str(e)[:300]}
    finally:
        _sync_status["is_running"] = False


def start_backfill_background(force: bool = False) -> Dict:
    """Kick off a backfill in a daemon thread; returns immediately."""
    if _sync_status["is_running"]:
        return {"status": "already_running", "message": "Ya hay una sincronización en progreso."}
    threading.Thread(target=run_backfill, kwargs={"force": force}, daemon=True).start()
    return {
        "status": "started",
        "message": "Backfill SIB iniciado en segundo plano (3–5 min). "
                   "Consulte el estado en esta misma pantalla.",
    }
