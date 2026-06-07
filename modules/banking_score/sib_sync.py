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
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
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

# Sync status lives in the DB (AppSetting) so it's shared across uvicorn workers —
# an in-memory dict was invisible to the worker handling the status poll, making a
# running backfill look dead. Treated as stale after this many seconds.
_STATUS_KEY = "sib_sync_status"
_STALE_SECONDS = 30 * 60
_lock = threading.Lock()

_DEFAULT_STATUS: Dict = {
    "is_running": False,
    "phase": "",
    "started_at": None,
    "last_sync": None,
    "last_check": None,
    "next_scheduled": None,
    "backfill_done": False,
    "last_sync_result": None,
    "alerts": [],
}


def _read_status(db: Session) -> Dict:
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _STATUS_KEY).first()
    except Exception:  # noqa: BLE001 — table may not exist yet (pre-migration/tests)
        db.rollback()
        return dict(_DEFAULT_STATUS)
    if row and row.value:
        try:
            return {**_DEFAULT_STATUS, **json.loads(row.value)}
        except (ValueError, TypeError):
            pass
    return dict(_DEFAULT_STATUS)


def _write_status(db: Session, **updates) -> Dict:
    st = _read_status(db)
    st.update(updates)
    payload = json.dumps(st)
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _STATUS_KEY).first()
        if row:
            row.value = payload
            row.is_secret = False
        else:
            db.add(AppSetting(key=_STATUS_KEY, value=payload, is_secret=False))
        db.commit()
    except Exception:  # noqa: BLE001 — never let status persistence break the run
        db.rollback()
    return st


def get_sync_status(db: Optional[Session] = None) -> Dict:
    own = db is None
    db = db or SessionLocal()
    try:
        st = _read_status(db)
        # Clear a stale "running" flag (e.g. worker died mid-run) so the UI recovers.
        if st.get("is_running") and st.get("started_at"):
            try:
                started = datetime.fromisoformat(st["started_at"])
                if (datetime.now(timezone.utc) - started).total_seconds() > _STALE_SECONDS:
                    st = _write_status(db, is_running=False, phase="(interrumpido)")
            except (ValueError, TypeError):
                pass
        return st
    finally:
        if own:
            db.close()


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

    Synchronous — callers run it in a background thread. Drives the DB-backed
    sync status so progress is visible across all workers, and returns a summary.
    """
    db = SessionLocal()
    try:
        with _lock:
            current = get_sync_status(db)
            if current.get("is_running"):
                return {"status": "already_running", "message": "Ya hay una sincronización en progreso."}
            _write_status(db, is_running=True, phase="iniciando", started_at=_now(),
                          last_check=_now())

        if not force and not needs_backfill(db):
            _write_status(db, is_running=False, phase="")
            return {
                "status": "skipped",
                "message": "Ya hay datos reales del SIB (source=sib_api). Use force=true para re-ejecutar.",
            }

        client = get_sib_data_client(force_new=True)
        if client is None:
            msg = "Clave del SIB no configurada. Configúrela en Configuración → APIs de Benchmarks por Sector."
            _write_status(db, is_running=False, phase="error", alerts=(current.get("alerts") or [])[-49:] + [msg])
            return {"status": "error", "message": msg}

        _write_status(db, phase="probando conexión")
        conn = client.check_connectivity()
        if not conn.get("reachable"):
            msg = f"No se pudo alcanzar la API del SIB ({conn.get('status_code')}). ¿Proxy configurado?"
            _write_status(db, is_running=False, phase="error", alerts=(current.get("alerts") or [])[-49:] + [msg])
            return {"status": "error", "message": msg, "connectivity": conn}

        _write_status(db, phase="descubriendo tipos de entidad")
        tipos = client.get_working_tipos()
        if not tipos:
            msg = "El SIB no devolvió ningún tipo de entidad válido."
            _write_status(db, is_running=False, phase="error", alerts=(current.get("alerts") or [])[-49:] + [msg])
            return {"status": "error", "message": msg}

        # Incremental + idempotent: fetch and WRITE one tipoEntidad at a time,
        # committing after each. Data lands progressively (visible in stats) and a
        # restart only loses the in-progress type — a re-run upserts the rest.
        created = updated = matched = skipped_period = 0
        errors: list = []
        unmatched: list = []
        for i, tipo in enumerate(tipos, 1):
            _write_status(db, phase=f"extrayendo {tipo} ({i}/{len(tipos)})… (puede tardar)")
            bulk = client.extract_one_tipo(tipo, period_start=period_start)
            unmatched += bulk.get("_unmatched", [])
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
            db.commit()  # persist this tipo before moving on (incremental)
            _write_status(db, phase=f"{tipo} listo ({i}/{len(tipos)}) · {matched} entidades, {created + updated} registros")

        result = {
            "status": "completed",
            "entities_matched": matched,
            "records_created": created,
            "records_updated": updated,
            "periods_skipped_non_quarterly": skipped_period,
            "unmatched": unmatched,
            "errors": errors[:20],
        }
        _write_status(db, is_running=False, phase="completado", last_sync=_now(),
                      backfill_done=True, last_sync_result=result)
        logger.info("SIB backfill: %s", result)
        return result
    except Exception as e:  # noqa: BLE001 — report any failure into status
        logger.exception("SIB backfill failed")
        try:
            _write_status(db, is_running=False, phase="error",
                          alerts=(_read_status(db).get("alerts") or [])[-49:] + [str(e)[:200]])
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "message": str(e)[:300]}
    finally:
        db.close()


def start_backfill_background(force: bool = False) -> Dict:
    """Start the backfill: via the Celery worker when enabled (survives web
    restarts, auto-retries on crash), otherwise an in-process thread.
    """
    from shared.config.settings import settings

    if get_sync_status().get("is_running"):
        return {"status": "already_running", "message": "Ya hay una sincronización en progreso."}

    msg = ("Backfill SIB iniciado en segundo plano. La extracción es incremental "
           "(los datos van apareciendo por tipo); puede tardar 10–20 min y el estado "
           "se actualiza en esta pantalla.")

    if settings.USE_CELERY and settings.REDIS_URL:
        try:
            from modules.banking_score.tasks import sib_backfill_task
            sib_backfill_task.delay(force=force)
            return {"status": "started", "via": "celery", "message": msg}
        except Exception:  # noqa: BLE001 — fall back to thread if broker unavailable
            logger.exception("No se pudo encolar en Celery; usando hilo")

    threading.Thread(target=run_backfill, kwargs={"force": force}, daemon=True).start()
    return {"status": "started", "via": "thread", "message": msg}
