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
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
# Register the 'users' table in Base.metadata: BankingData.uploaded_by (and
# RatingResult/RatingAction.*_by) carry a ForeignKey("users.id"). The Celery worker
# doesn't import the auth routers, so without this the backfill's DB write fails with
# NoReferencedTableError ('users' not found). See docs/DEEP_DIVE_FITCH_PARITY.md.
import shared.auth.models  # noqa: F401
from modules.banking_score.external.sib_data_client import (
    EIC_TIPOS,
    SIB_ENTITY_CODES,
    get_sib_data_client,
)
from modules.banking_score.external.simbad_client import extract_cambiaria_bulk
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    BankType,
    DataSource,
    PeriodType,
    RatingResult,
)
from modules.banking_score.seed.banking_seed import BANKING_ENTITIES

logger = logging.getLogger("sdq.banking.sib_sync")

# Official bank name per SIB short name (seed shorts match the SIB catalog 1:1).
_SHORT_TO_NAME = {e["short"]: e["name"] for e in BANKING_ENTITIES}

# SIB tipoEntidad code → our BankType. Extend here when a new category is added
# to the catalog (e.g. agentes de cambio → cambiaria, fiduciarias → fiduciaria).
_TIPO_TO_BANKTYPE = {
    "BM": BankType.banca_multiple,
    "AAP": BankType.aap,
    "BAC": BankType.banco_ahorro_credito,
    "CC": BankType.corporacion_credito,
    # Intermediación cambiaria (EIC): agentes de remesas/cambio y de cambio.
    "ARC": BankType.cambiaria,
    "AC": BankType.cambiaria,
}

# Sync status lives in the DB (AppSetting) so it's shared across uvicorn workers —
# an in-memory dict was invisible to the worker handling the status poll, making a
# running backfill look dead. Treated as stale after this many seconds.
_STATUS_KEY = "sib_sync_status"
_STALE_SECONDS = 30 * 60
# A backfill that completed within this window is treated as an accidental duplicate
# (e.g. a double-click) and skipped. The Celery re-delivery STORM is prevented at the
# source by broker visibility_timeout (6h) > run duration, so this only needs to guard
# rapid double-triggers — kept short so a deliberate re-run isn't blocked for hours.
_DEDUP_WINDOW_SECONDS = 15 * 60
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
    st["heartbeat"] = datetime.now(timezone.utc).isoformat()  # liveness, per update
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
        # Clear a stale "running" flag only if there's been no heartbeat for a
        # while (worker truly died) — not merely because the job is long-running.
        ref = st.get("heartbeat") or st.get("started_at")
        if st.get("is_running") and ref:
            try:
                last = datetime.fromisoformat(ref)
                if (datetime.now(timezone.utc) - last).total_seconds() > _STALE_SECONDS:
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
    by_source = {
        src.value: cnt
        for src, cnt in db.query(BankingData.source, func.count(BankingData.id))
        .group_by(BankingData.source)
        .all()
    }
    sib_records = by_source.get(DataSource.sib_api.value, 0)
    return {
        "entities": entities,
        "records": records,
        "ratings": ratings,
        "sib_records": sib_records,
        # Per-source breakdown surfaces any residual synthetic (manual) fixture so
        # it can never hide among the real sources (sib_api/simbad/csv_upload).
        "by_source": by_source,
        "synthetic_records": by_source.get(DataSource.manual.value, 0),
        "period_start": str(rng[0]) if rng and rng[0] else None,
        "period_end": str(rng[1]) if rng and rng[1] else None,
    }


def prune_future_periods(db: Session) -> Dict[str, int]:
    """Remove data/ratings for quarters that haven't closed yet (period_end in
    the future). The SIB returns the in-progress quarter with partial figures
    (no solvency/capital published), which would score as a bogus SDQ-D and
    poison the "latest" rankings. These rows regenerate once the quarter closes.
    """
    today = date.today()
    from modules.banking_score.models.models import RatingAction

    ra = db.query(RatingAction).filter(RatingAction.period_end > today).delete(synchronize_session=False)
    rr = db.query(RatingResult).filter(RatingResult.period_end > today).delete(synchronize_session=False)
    bd = db.query(BankingData).filter(BankingData.period_end > today).delete(synchronize_session=False)
    db.commit()
    if bd or rr or ra:
        logger.info("Pruned future periods (> %s): %d data, %d ratings, %d actions", today, bd, rr, ra)
    return {"data_deleted": bd, "ratings_deleted": rr, "actions_deleted": ra}


# Coverage below which the most-recent quarter is deemed "still partial" (the SIB
# publishes quarterly statements with a lag, so a just-closed quarter is queried the
# day after close with only a handful of early filers). Extreme (< half the prior
# quarter) so it never trips on legitimate panel changes.
_PARTIAL_QUARTER_COVERAGE = 0.5


def prune_partial_latest_quarter(db: Session, min_coverage: float = _PARTIAL_QUARTER_COVERAGE) -> Dict:
    """Drop the most-recent quarter(s) whose SIB data is still partial.

    The ``period_end > today`` guard only catches genuinely future quarters. A
    quarter that closed a day or two ago is *past* yet the SIB has only published a
    fraction of the panel — an incomplete, inflated "latest" ranking (and, when the
    carteras cube hasn't landed, N/D concentration/HHI that lifts calidad). We detect
    it by coverage: a partial quarter has far fewer entities than the prior complete
    one. Self-calibrating — no publication-lag magic number. Loops in case more than
    one trailing quarter is partial.
    """
    from modules.banking_score.models.models import RatingAction

    pruned = {"data_deleted": 0, "ratings_deleted": 0, "actions_deleted": 0, "periods": []}
    while True:
        counts = (
            db.query(BankingData.period_end,
                     func.count(func.distinct(BankingData.bank_id)))
            .group_by(BankingData.period_end)
            .order_by(BankingData.period_end.desc())
            .all()
        )
        if len(counts) < 2:
            break
        (latest_pe, latest_n), (_, prev_n) = counts[0], counts[1]
        if prev_n <= 0 or latest_n >= min_coverage * prev_n:
            break  # latest quarter has adequate coverage → treat as complete
        pruned["actions_deleted"] += db.query(RatingAction).filter(
            RatingAction.period_end == latest_pe).delete(synchronize_session=False)
        pruned["ratings_deleted"] += db.query(RatingResult).filter(
            RatingResult.period_end == latest_pe).delete(synchronize_session=False)
        pruned["data_deleted"] += db.query(BankingData).filter(
            BankingData.period_end == latest_pe).delete(synchronize_session=False)
        db.commit()
        pruned["periods"].append(str(latest_pe))
        logger.info("Pruned partial quarter %s (%d entities vs %d in the prior quarter)",
                    latest_pe, latest_n, prev_n)
    return pruned


def purge_synthetic_data(db: Session) -> Dict[str, int]:
    """Delete all synthetic seed data (``source=manual``) and any ratings/actions
    left orphaned by the deletion.

    ``manual`` is produced by nothing anymore (the seed was sealed to catalog-only)
    and the scoring already ignores it; this clears any residue from before the
    seal so the DB holds only real data. A rating/action is orphaned when its
    (bank, period) no longer has *any* backing ``BankingData`` row — that happens
    only for pure-manual (bank, period) pairs; periods that also hold real data
    keep their real ratings untouched.
    """
    from sqlalchemy import and_, exists

    from modules.banking_score.models.models import RatingAction

    bd = (
        db.query(BankingData)
        .filter(BankingData.source == DataSource.manual)
        .delete(synchronize_session=False)
    )
    db.commit()

    backed = lambda model: exists().where(and_(  # noqa: E731 — terse local predicate
        BankingData.bank_id == model.bank_id,
        BankingData.period_end == model.period_end,
    ))
    ra = db.query(RatingAction).filter(~backed(RatingAction)).delete(synchronize_session=False)
    rr = db.query(RatingResult).filter(~backed(RatingResult)).delete(synchronize_session=False)
    db.commit()

    if bd or rr or ra:
        logger.info("Purged synthetic data: %d manual records, %d orphan ratings, %d orphan actions",
                    bd, rr, ra)
    return {"synthetic_deleted": bd, "orphan_ratings_deleted": rr, "orphan_actions_deleted": ra}


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


def _match_or_create_bank(db: Session, short_name: str, extra_codes: Optional[Dict] = None):
    """Find the bank for a SIB short name, or AUTO-CREATE it if it's in the SIB
    catalog (or in *extra_codes*, a per-run dynamic catalog used for cambiarias
    discovered live) but not yet in the DB — so new supervised entities appear
    automatically.

    Returns (bank, created). bank is None if the entity isn't catalogued or its
    type maps to no BankType (then the caller raises a "new entity" alert).
    """
    info = SIB_ENTITY_CODES.get(short_name) or (extra_codes or {}).get(short_name) or {}
    name = _SHORT_TO_NAME.get(short_name) or info.get("nombre") or (info.get("nombre_sib") or "").title()
    if not name:
        return None, False
    bank = db.query(Bank).filter(Bank.name == name).first()
    if bank:
        return bank, False
    bank_type = _TIPO_TO_BANKTYPE.get(info.get("tipo_entidad"))
    if not bank_type:
        return None, False  # unknown category → not auto-created (alerted instead)
    bank = Bank(
        name=name,
        bank_type=bank_type,
        sib_code=info.get("sib_code"),
        is_active=info.get("active", True),  # exited entities catalogued inactive
    )
    db.add(bank)
    db.flush()  # assign id
    logger.info("Auto-registered new SIB entity: %s (%s)", name, bank_type.value)
    return bank, True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fase_actual(db) -> Optional[str]:
    """La fase que el estado traía ANTES de pisarla con «error»: dice DÓNDE murió."""
    try:
        return (get_sync_status(db) or {}).get("phase")
    except Exception:  # noqa: BLE001 — el diagnóstico nunca puede romper el manejo del error
        return None


def _firma_tecnica(exc: Exception, fase: Optional[str]) -> Dict[str, Optional[str]]:
    """Tipo de excepción, mensaje acotado y fase — lo mínimo para diagnosticar sin logs.

    El mensaje se trunca porque un error de driver puede traer una consulta entera, y el
    estado se sirve por API a la pantalla de Datos.
    """
    return {
        "excepcion": type(exc).__name__,
        "detalle": str(exc)[:300] or None,
        "fase_al_fallar": fase,
    }


def _friendly_error(exc: Exception) -> str:
    """Translate a raw exception into a clear Spanish message for the UI.
    The full technical detail stays in the logs, not in front of the operator.
    """
    text = str(exc).lower()
    if "enum" in text or "invalidtextrepresentation" in text:
        return ("Error de configuración de la base (un tipo de entidad no estaba "
                "registrado). Reintenta la sincronización.")
    if "timeout" in text or "timed out" in text:
        return "Tiempo de espera agotado al consultar la API del SIB. Reintenta."
    if "connect" in text or "connection" in text:
        return "No se pudo conectar con la API del SIB. Revisa la clave y el proxy."
    if "ocp-apim" in text or "401" in text or "subscription" in text:
        return "Credenciales del SIB inválidas. Revísalas en Configuración."
    return "Ocurrió un error durante la sincronización. El detalle quedó en los registros (logs)."


def run_backfill(force: bool = False, period_start: str = "2021-01",
                 only_tipos: Optional[List[str]] = None,
                 skip_carteras: bool = False) -> Dict:
    """Replace synthetic data with real SIB data (quarter-end periods only).

    Synchronous — callers run it in a background thread. Drives the DB-backed
    sync status so progress is visible across all workers, and returns a summary.

    *only_tipos* (e.g. ``["BAC", "AAP"]``) restricts the run to those entity
    types — a targeted re-ingest that skips the slow BM carteras stream. When it
    excludes the cambiaria types (ARC/AC), the SIMBAD cambiaria fallback is
    skipped too.

    *skip_carteras* omits the per-quarter loan-cube aggregation (the 504s-prone
    long pole). The income/balance/indicators/solvency fields are re-ingested
    fresh; the carteras-derived fields (hhi_sectorial_raw, cartera_total,
    suma_top10) are left as-is (the upsert only writes non-None fields). Use it
    for a fast, robust re-ingest that only needs the income statement (e.g. a
    cost-to-income recalibration).
    """
    db = SessionLocal()
    try:
        with _lock:
            current = get_sync_status(db)
            if current.get("is_running"):
                return {"status": "already_running", "message": "Ya hay una sincronización en progreso."}
            # Dedup: Celery (acks_late) re-delivers a long-running task after the
            # broker visibility timeout, so the same backfill executes again — a
            # storm of redundant full runs. Skip if one completed very recently;
            # a re-delivered duplicate just acks out instead of re-ingesting.
            last_sync = current.get("last_sync")
            if not force and current.get("backfill_done") and last_sync:  # force = admin override
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_sync)).total_seconds()
                    if age < _DEDUP_WINDOW_SECONDS:
                        logger.warning("Skipping duplicate backfill (last completed %.0f min ago)", age / 60)
                        return {
                            "status": "skipped_duplicate",
                            "message": f"Un backfill terminó hace {age / 60:.0f} min; se omite la corrida duplicada.",
                        }
                except (ValueError, TypeError):
                    pass
            # Clear stale alerts so each run reports only its own state
            # (otherwise an old error sticks around forever).
            _write_status(db, is_running=True, phase="iniciando", started_at=_now(),
                          last_check=_now(), alerts=[])

        if not force and not needs_backfill(db):
            _write_status(db, is_running=False, phase="")
            return {
                "status": "skipped",
                "message": "Ya hay datos reales del SIB (source=sib_api). Use force=true para re-ejecutar.",
            }

        client = get_sib_data_client(force_new=True)
        if client is None:
            msg = "Clave del SIB no configurada. Configúrela en Configuración → APIs de Benchmarks por Sector."
            _write_status(db, is_running=False, phase="error", alerts=[msg])
            return {"status": "error", "message": msg}

        _write_status(db, phase="probando conexión")
        conn = client.check_connectivity()
        if not conn.get("reachable"):
            msg = "No se pudo alcanzar la API del SIB. Revisa la clave y el proxy en Configuración."
            _write_status(db, is_running=False, phase="error", alerts=[msg])
            return {"status": "error", "message": msg, "connectivity": conn}

        _write_status(db, phase="descubriendo tipos de entidad")
        tipos = client.get_working_tipos()
        if not tipos:
            msg = "El SIB no devolvió ningún tipo de entidad válido."
            _write_status(db, is_running=False, phase="error", alerts=[msg])
            return {"status": "error", "message": msg}

        # Targeted re-ingest: restrict to requested types (preserve discovery order).
        if only_tipos:
            wanted = {t.strip().upper() for t in only_tipos}
            tipos = [t for t in tipos if t.upper() in wanted]
            if not tipos:
                msg = f"Ninguno de los tipos solicitados está disponible: {sorted(wanted)}"
                _write_status(db, is_running=False, phase="error", alerts=[msg])
                return {"status": "error", "message": msg}
            logger.info("Backfill dirigido a tipos: %s", tipos)

        # Drop any in-progress/future quarter left over from a prior run before
        # ingesting fresh data (keeps the "latest" rankings on closed quarters).
        prune_future_periods(db)

        # Incremental + idempotent: fetch and WRITE one tipoEntidad at a time,
        # committing after each. Data lands progressively (visible in stats) and a
        # restart only loses the in-progress type — a re-run upserts the rest.
        today = date.today()
        created = updated = matched = skipped_period = skipped_future = entities_created = 0
        errors: list = []
        unmatched: list = []
        for i, tipo in enumerate(tipos, 1):
            _write_status(db, phase=f"extrayendo {tipo} ({i}/{len(tipos)})… (puede tardar)")

            # Refresh the heartbeat during the long carteras/creditos aggregation
            # (a quarter is ~100k+ rows). Without it the per-tipo status goes stale
            # and get_sync_status false-flags the live run as "(interrumpido)".
            def _progress(msg: str, _i=i, _tipo=tipo) -> None:
                _write_status(db, is_running=True,
                              phase=f"extrayendo {_tipo} ({_i}/{len(tipos)}) · {msg}")

            # EL DESGLOSE SECTORIAL SE ESCRIBE Y SE COMMITEA POR TRIMESTRE, no al final.
            # Dos backfills murieron el 2026-08-30 —106 y 107 minutos— y los dos tiraron
            # todo lo agregado hasta ese punto, porque la escritura ocurría después de los
            # veintidós. Ahora un fallo cuesta un trimestre.
            def _escribir_trimestre(pe, por_entidad, _tipo=tipo) -> None:
                escritas = 0
                for short, celdas in por_entidad.items():
                    bank, _ = _match_or_create_bank(db, short)
                    if not bank:
                        continue
                    _guardar_cartera_sectorial(db, bank.id, pe, celdas)
                    escritas += len(celdas)
                db.commit()
                logger.info("[sib] desglose sectorial %s (%s): %d celdas", pe, _tipo, escritas)

            bulk = client.extract_one_tipo(tipo, period_start=period_start,
                                           on_progress=_progress, skip_carteras=skip_carteras,
                                           on_quarter=_escribir_trimestre)
            unmatched += bulk.get("_unmatched", [])
            entity_meta = bulk.get("_entity_meta", {})  # cambiarias: live dynamic catalog
            for short_name, periods in bulk.items():
                if short_name.startswith("_"):
                    continue
                bank, was_created = _match_or_create_bank(db, short_name, extra_codes=entity_meta)
                if not bank:
                    errors.append(f"{short_name}: entidad no catalogada")
                    continue
                if was_created:
                    entities_created += 1
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
                    # Skip the in-progress/future quarter — its data is partial
                    # (no solvency yet) and would score as a bogus SDQ-D.
                    if pe > today:
                        skipped_future += 1
                        continue
                    existing = (
                        db.query(BankingData)
                        .filter_by(bank_id=bank.id, period_end=pe)
                        .first()
                    )
                    row = existing or BankingData(bank_id=bank.id, period_end=pe)
                    row.period_type = PeriodType.quarterly
                    row.source = DataSource.sib_api
                    # El desglose sectorial NO es una columna de BankingData: se saca antes
                    # del setattr y se persiste en su propia tabla.
                    _guardar_cartera_sectorial(db, bank.id, pe, rec.pop("_por_sector", None))
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

        # ── SIMBAD fallback (cambiarias) ───────────────────────────────────────
        # The open API doesn't publish AC cambiarias for recent quarters (verified
        # 2026); SIMBAD (public Superset of the SB) does. Fill any cambiaria
        # (entity × quarter-end) the API pass didn't produce. API stays PRIMARY:
        # never overwrite an existing row. Best-effort — must not break the backfill.
        simbad_created = 0
        # Only relevant when the run includes cambiaria types — a targeted
        # BAC/AAP re-ingest has no cambiarias to fill, so skip the SIMBAD pass.
        if any(t.upper() in EIC_TIPOS for t in tipos):
            try:
                _write_status(db, phase="SIMBAD: completando cambiarias faltantes…")
                simbad = extract_cambiaria_bulk(period_start=period_start)
                simbad_meta = simbad.get("_entity_meta", {})
                for short_name, speriods in simbad.items():
                    if short_name.startswith("_"):
                        continue
                    bank, was_created = _match_or_create_bank(db, short_name, extra_codes=simbad_meta)
                    if not bank:
                        continue
                    if was_created:
                        entities_created += 1
                    for rec in speriods:
                        rec = dict(rec)
                        pe = rec.pop("period_end")
                        rec.pop("period_type", None)
                        rec.pop("source", None)
                        if pe.month not in (3, 6, 9, 12) or pe > today:
                            continue
                        if db.query(BankingData).filter_by(bank_id=bank.id, period_end=pe).first():
                            continue  # API primary — leave its row untouched
                        row = BankingData(bank_id=bank.id, period_end=pe,
                                          period_type=PeriodType.quarterly, source=DataSource.sib_simbad)
                        for k, v in rec.items():
                            if v is not None:
                                setattr(row, k, v)
                        db.add(row)
                        simbad_created += 1
                db.commit()
                created += simbad_created
                _write_status(db, phase=f"SIMBAD: {simbad_created} períodos de cambiarias completados")
            except Exception as e:  # noqa: BLE001 — fallback must never break the API backfill
                db.rollback()
                logger.warning("SIMBAD fallback falló (no crítico): %s", e)
                _write_status(db, phase="SIMBAD: fallback omitido (ver logs)")

        # Drop any just-closed quarter the SIB has only partially published (queried
        # the day after close). Runs AFTER ingest (the future-prune at the start can't
        # catch it — the ingest re-adds it) and BEFORE scoring, so partial quarters
        # never reach the rankings.
        _write_status(db, phase="podando trimestre parcial (si lo hay)")
        prune_partial_latest_quarter(db)

        # Recalculate ratings for the freshly-ingested SIB data. Without this the
        # platform has real data but stale/missing ratings (834 records vs 70
        # ratings). Runs in the same session, oldest period first so rating-action
        # deltas build chronologically; progress is visible in the sync status.
        from modules.banking_score.scoring.batch import score_all_periods

        def _scoring_progress(i: int, total: int, pe) -> None:
            _write_status(db, phase=f"calculando ratings {pe} ({i}/{total})…")

        scoring = score_all_periods(db, only_sib=True, on_progress=_scoring_progress)

        # Level 2: SIB returned entities we don't catalog → alert to add them.
        # Fresh list (alerts were cleared at start) so no stale errors linger.
        new_alerts: list = []
        uniq_unmatched = sorted({u for u in unmatched if u and u != "TODOS"})
        if uniq_unmatched:
            new_alerts = [
                "Entidades del SIB no catalogadas (agrégalas al catálogo): "
                + ", ".join(uniq_unmatched[:15])
            ]

        result = {
            "status": "completed",
            "entities_matched": matched,
            "entities_created": entities_created,
            "records_created": created,
            "records_updated": updated,
            "periods_skipped_non_quarterly": skipped_period,
            "periods_skipped_future": skipped_future,
            "ratings_written": scoring["ratings_written"],
            "ratings_total": scoring["ratings_total"],
            "periods_scored": scoring["periods_scored"],
            "unmatched": uniq_unmatched,
            "errors": errors[:20],
        }
        _write_status(db, is_running=False, phase="completado", last_sync=_now(),
                      backfill_done=True, last_sync_result=result, alerts=new_alerts)
        logger.info("SIB backfill: %s", result)
        return result
    except Exception as e:  # noqa: BLE001 — report any failure into status
        logger.exception("SIB backfill failed")  # full technical detail → logs
        friendly = _friendly_error(e)
        # LA FIRMA TÉCNICA TAMBIÉN SE PERSISTE. El mensaje amable sigue en `alerts` —un
        # stacktrace no va delante del operador— pero mandar el detalle SOLO a los logs deja
        # irrecuperable el fallo de una operación de dos horas y media para quien no tenga
        # acceso al servidor. Pasó el 2026-08-30: el backfill murió en el trimestre 19 de 22
        # y lo único que quedó fue «el detalle está en los registros».
        tecnico = _firma_tecnica(e, _fase_actual(db))
        try:
            _write_status(db, is_running=False, phase="error", alerts=[friendly],
                          last_sync_result={"status": "error", "message": friendly, **tecnico})
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "message": friendly, **tecnico}
    finally:
        db.close()


def start_backfill_background(force: bool = False,
                              only_tipos: Optional[List[str]] = None,
                              skip_carteras: bool = False) -> Dict:
    """Start the backfill: via the Celery worker when enabled (survives web
    restarts, auto-retries on crash), otherwise an in-process thread.

    *only_tipos* restricts the run to the given entity types (targeted re-ingest).
    *skip_carteras* omits the slow per-quarter loan-cube aggregation (see run_backfill).
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
            sib_backfill_task.delay(force=force, only_tipos=only_tipos, skip_carteras=skip_carteras)
            return {"status": "started", "via": "celery", "message": msg}
        except Exception:  # noqa: BLE001 — fall back to thread if broker unavailable
            logger.exception("No se pudo encolar en Celery; usando hilo")

    threading.Thread(target=run_backfill,
                     kwargs={"force": force, "only_tipos": only_tipos,
                             "skip_carteras": skip_carteras}, daemon=True).start()
    return {"status": "started", "via": "thread", "message": msg}


# ─── Targeted recompute of carteras-cube metrics (one quarter) ───
# Re-streams only carteras/creditos for a single period to populate the loan-book
# fields (mayores deudores → suma_top10, total, vigente A, vencida) and rescore —
# far faster than the full ~3h backfill, for iterating on the concentration data.

def _guardar_cartera_sectorial(db, bank_id: str, pe, por_sector: Any) -> None:
    """Reescribe el desglose sectorial de una entidad y corte.

    Se BORRA y se reinserta en vez de actualizar fila por fila porque el conjunto de sectores
    de una entidad cambia entre cortes: si una entidad deja de prestarle a un sector, un
    upsert dejaría la fila vieja para siempre y el sector aparecería como exposición viva.
    Es la misma razón por la que el total y el desglose tienen que reconciliar.

    Un corte sin desglose NO borra lo que ya había: significa que el cubo no trajo sectores
    para esa entidad, y «no vino el dato» no es «ya no presta a nadie».
    """
    if not por_sector:
        return
    from modules.banking_score.models.models import CarteraSectorial
    db.query(CarteraSectorial).filter_by(bank_id=bank_id, period_end=pe).delete(
        synchronize_session=False)
    for celda in por_sector:
        db.add(CarteraSectorial(
            bank_id=bank_id, period_end=pe,
            sector=str(celda.get("sector") or "")[:160],
            provincia=str(celda.get("provincia") or "SIN PROVINCIA")[:80],
            region=(str(celda["region"])[:80] if celda.get("region") else None),
            # Las medidas se copian por NOMBRE desde la celda: agregar un campo al cubo
            # no obliga a tocar esta lista, que es donde se olvidaría.
            **{k: celda.get(k) for k in (
                "deuda", "vencida", "vencida_31_90", "garantia", "provision", "creditos",
                "desembolso", "deuda_capital", "plasticos", "tasa_por_deuda",
                "deuda_con_tasa", "deuda_moneda_extranjera", "deuda_persona_fisica",
                "cartera_a", "cartera_b", "cartera_c", "cartera_d", "cartera_e")}))


def recompute_carteras_metrics(period: str, write_status=None) -> Dict:
    """Stream carteras/creditos for *period* (YYYY-MM), update the cartera fields on
    existing BankingData rows, and rescore the affected periods.

    *write_status* lets a caller redirect progress to its own status store (e.g. the
    operation console's per-op status). Defaults to the SIB sync status for the
    legacy standalone trigger.
    """
    write_status = write_status or _write_status
    db = SessionLocal()
    try:
        write_status(db, is_running=True, phase=f"recomputando carteras {period}",
                      started_at=_now(), result=None)
        client = get_sib_data_client(force_new=True)
        if client is None:
            write_status(db, is_running=False, phase="error",
                          last_sync_result={"error": "Sin cliente SIB (¿falta la clave?)."})
            return {"error": "Sin cliente SIB."}

        metrics = client._compute_carteras_metrics(
            period, period, on_progress=lambda m: write_status(db, phase=m))

        updated = 0
        affected_periods: set = set()
        for short_name, by_pe in metrics.items():
            if short_name.startswith("_"):
                continue
            bank, _created = _match_or_create_bank(db, short_name)
            if not bank:
                continue
            for pe, cm in by_pe.items():
                row = db.query(BankingData).filter_by(bank_id=bank.id, period_end=pe).first()
                if not row:
                    continue  # only enrich existing rows (balance/income already loaded)
                # El desglose sectorial ensanchó el tipo del dict de métricas (trae un dict
                # anidado), así que los escalares se acotan acá en vez de dejar que `Any` se
                # propague a las columnas.
                total = float(cm.get("total") or 0)
                if total <= 0:
                    continue
                row.cartera_total = total
                mayores = cm.get("mayores")
                row.suma_top10 = None if mayores is None else float(mayores)
                if cm.get("hhi") is not None:
                    row.hhi_sectorial_raw = cm["hhi"]
                if cm.get("cartera_a"):
                    row.cartera_categoria_a = cm["cartera_a"]
                if cm.get("vencida"):
                    row.cartera_vencida_90d = cm["vencida"]
                _guardar_cartera_sectorial(db, bank.id, pe, cm.get("por_sector") or {})
                updated += 1
                affected_periods.add(pe)
        db.commit()

        from modules.banking_score.scoring.batch import score_period
        ratings = 0
        for pe in sorted(affected_periods):
            ratings += score_period(db, pe).get("scored", 0)

        result = {"rows_updated": updated, "periods": len(affected_periods), "ratings_written": ratings}
        write_status(db, is_running=False, phase="completado",
                      last_sync=_now(), last_sync_result=result)
        return result
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.exception("recompute_carteras_metrics falló")
        write_status(db, is_running=False, phase="error",
                      last_sync_result={"error": _friendly_error(e)})
        return {"error": _friendly_error(e)}
    finally:
        db.close()


def start_recompute_carteras_background(period: str) -> Dict:
    """Kick off recompute_carteras_metrics in a daemon thread."""
    st = get_sync_status()
    if st.get("is_running"):
        return {"started": False, "reason": "Ya hay una sincronización en curso."}
    threading.Thread(target=recompute_carteras_metrics, kwargs={"period": period}, daemon=True).start()
    return {"started": True, "period": period}
