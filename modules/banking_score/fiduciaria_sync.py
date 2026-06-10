"""Fiduciary ingestion — orchestrates the audited-PDF ETL → persistence → scoring.

Entities (sociedades fiduciarias): extract each entity-year PDF, map to BankingData
fields, compute the income HHI, upsert, then score with the ``fiduciaria`` profile —
reusing the existing rating tables and UI (Bank.bank_type=fiduciaria).

Public trusts (fideicomisos): extract each trust PDF, map to FideicomisoData, compute
the health index (own scale), upsert FideicomisoHealthScore.

Status/progress live in the DB (AppSetting) so they're visible across workers — same
pattern as ``sib_sync``. Errors are translated to clear Spanish for the UI.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from shared.database.session import SessionLocal
from shared.settings.models import AppSetting
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    BankType,
    DataSource,
    Fideicomiso,
    FideicomisoData,
    FideicomisoHealthScore,
    PeriodType,
)
from modules.banking_score.external import fiduciaria_pdf_client as fc
from modules.banking_score.scoring.batch import score_period
from modules.banking_score.scoring.fideicomiso import compute_health

logger = logging.getLogger("sdq.banking_score.fiduciaria_sync")

_STATUS_KEY = "fiduciaria_sync_status"
_STALE_SECONDS = 3600
_DEFAULT_STATUS = {
    "is_running": False, "phase": "inactivo", "started_at": None, "last_sync": None,
    "heartbeat": None, "processed": 0, "total": 0, "current": None,
    "result": None, "error": None,
}
_lock = threading.Lock()


# ─── DB-persisted status (shared across workers) ─────────────────

def _read_status(db: Session) -> Dict:
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _STATUS_KEY).first()
    except Exception:  # noqa: BLE001
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
    st["heartbeat"] = datetime.now(timezone.utc).isoformat()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == _STATUS_KEY).first()
        if row:
            row.value = json.dumps(st)
            row.is_secret = False
        else:
            db.add(AppSetting(key=_STATUS_KEY, value=json.dumps(st), is_secret=False))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return st


def get_fiduciaria_status(db: Optional[Session] = None) -> Dict:
    own = db is None
    db = db or SessionLocal()
    try:
        st = _read_status(db)
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


def _friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "anthropic" in text or "api key" in text or "clave" in text:
        return "Falta o es inválida la clave de Anthropic (ANTHROPIC_API_KEY) para la extracción con IA."
    if "timeout" in text or "timed out" in text:
        return "Tiempo de espera agotado al descargar o procesar un PDF. Reintenta."
    if "connect" in text or "connection" in text or "name or service" in text:
        return "No se pudo conectar con el portal de la SIB. Reintenta más tarde."
    return "Ocurrió un error durante la sincronización de fiduciarias. El detalle quedó en los logs."


# ─── Helpers ─────────────────────────────────────────────────────

def _get_or_create_bank(db: Session, name: str) -> Bank:
    bank = db.query(Bank).filter(Bank.name == name).first()
    if bank:
        if bank.bank_type != BankType.fiduciaria:
            bank.bank_type = BankType.fiduciaria
        return bank
    bank = Bank(name=name, bank_type=BankType.fiduciaria, is_active=True)
    db.add(bank)
    db.flush()
    logger.info("Auto-registrada fiduciaria: %s", name)
    return bank


def _income_hhi(comisiones: Optional[float], ingresos: Optional[float]) -> Optional[float]:
    """HHI of income concentration: comisiones fiduciarias vs other income."""
    if not ingresos or ingresos <= 0 or comisiones is None:
        return None
    c = max(min(comisiones / ingresos, 1.0), 0.0)
    otros = max(1.0 - c, 0.0)
    return round(c * c + otros * otros, 4)


def _upsert_banking_data(db: Session, bank_id: str, period_end: date, fields: Dict) -> BankingData:
    row = (
        db.query(BankingData)
        .filter_by(bank_id=bank_id, period_end=period_end)
        .first()
    )
    if not row:
        row = BankingData(bank_id=bank_id, period_end=period_end)
        db.add(row)
    row.period_type = PeriodType.annual
    row.source = DataSource.sib_pdf
    row.activos_totales = fields.get("activos_totales")
    row.pasivos_exigibles = fields.get("pasivos_exigibles")
    row.pasivos_cp = fields.get("pasivos_cp")
    row.patrimonio_tecnico = fields.get("patrimonio_tecnico")
    row.activos_liquidos = fields.get("activos_liquidos")
    row.ingresos_operacionales = fields.get("ingresos_operacionales")
    row.gastos_operacionales = fields.get("gastos_operacionales")
    row.utilidad_neta = fields.get("utilidad_neta")
    row.hhi_ingresos_raw = _income_hhi(fields.get("comisiones_fiduciarias"), fields.get("ingresos_operacionales"))
    db.flush()
    return row


def _get_or_create_trust(db: Session, name: str, fiduciaria_bank_id: str, slug: str, url: str) -> Fideicomiso:
    t = db.query(Fideicomiso).filter(Fideicomiso.name == name).first()
    if not t:
        t = Fideicomiso(name=name, slug=slug, fiduciaria_bank_id=fiduciaria_bank_id, source_url=url)
        db.add(t)
        db.flush()
    else:
        t.fiduciaria_bank_id = fiduciaria_bank_id
        t.source_url = url
    return t


def _upsert_trust_data(db: Session, trust_id: str, period_end: date, fields: Dict) -> None:
    row = db.query(FideicomisoData).filter_by(fideicomiso_id=trust_id, period_end=period_end).first()
    if not row:
        row = FideicomisoData(fideicomiso_id=trust_id, period_end=period_end)
        db.add(row)
    row.period_type = PeriodType.annual
    row.source = DataSource.sib_pdf
    row.activos_totales = fields.get("activos_totales")
    row.pasivos_totales = fields.get("pasivos_totales")
    row.pasivos_circulantes = fields.get("pasivos_circulantes")
    row.patrimonio_fideicomitido = fields.get("patrimonio_fideicomitido")
    row.activos_liquidos = fields.get("activos_liquidos")
    row.resultado_periodo = fields.get("resultado_periodo")
    row.ingresos_operacionales = fields.get("ingresos_operacionales")

    health = compute_health(fields)
    score = db.query(FideicomisoHealthScore).filter_by(fideicomiso_id=trust_id, period_end=period_end).first()
    if not score:
        score = FideicomisoHealthScore(fideicomiso_id=trust_id, period_end=period_end)
        db.add(score)
    score.solvencia_score = health["solvencia_score"]
    score.liquidez_score = health["liquidez_score"]
    score.sostenibilidad_score = health["sostenibilidad_score"]
    score.overall_score = health["overall_score"]
    score.health_band = health["health_band"]
    score.segment = health["segment"]
    # segment also on the trust record for filtering
    t = db.query(Fideicomiso).filter_by(id=trust_id).first()
    if t:
        t.segment = health["segment"]
    db.flush()


def _extract_one(url: str) -> Dict:
    """Download + AI-extract a PDF; return the raw statements dict."""
    from modules.banking_score.external.audited_pdf_extractor import AuditedPdfExtractor

    path = fc.download_pdf(url)
    try:
        return AuditedPdfExtractor().extract_statements(path)
    finally:
        import os

        if path and os.path.exists(path):
            os.remove(path)


# ─── Orchestration ───────────────────────────────────────────────

def run_fiduciaria_sync(include_trusts: bool = True, only_latest: bool = False) -> Dict:
    """Ingest fiduciary entities (+ public trusts). Idempotent (upsert by period)."""
    db = SessionLocal()
    errors: list[str] = []
    entities_done = 0
    trusts_done = 0
    scored_periods: set[date] = set()
    try:
        # Build the work list first (so we can report total/progress).
        plan = []  # (kind, entity_name, label, url, period_end|None)
        for slug, name in fc.FIDUCIARY_ENTITIES.items():
            try:
                disco = fc.discover_pdfs(slug)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: no se pudo leer la ficha ({e})")
                continue
            ents = disco["entity"]
            if only_latest and ents:
                ents = [ents[0]]
            for year, url in ents:
                if year:
                    plan.append(("entity", name, str(year), url, date(year, 12, 31)))
            if include_trusts:
                for tname, turl in disco["trusts"]:
                    plan.append(("trust", name, tname, turl, None))

        total = len(plan)
        _write_status(db, is_running=True, phase="extrayendo", started_at=datetime.now(timezone.utc).isoformat(),
                      processed=0, total=total, result=None, error=None)

        for i, (kind, ent_name, label, url, period_end) in enumerate(plan):
            _write_status(db, processed=i, current=f"{ent_name} · {label}", phase="extrayendo")
            try:
                statements = _extract_one(url)
                if kind == "entity":
                    fields = fc.map_entity_fields(statements)
                    bank = _get_or_create_bank(db, ent_name)
                    _upsert_banking_data(db, bank.id, period_end, fields)
                    db.commit()
                    scored_periods.add(period_end)
                    entities_done += 1
                else:
                    fields = fc.map_trust_fields(statements)
                    ci = statements.get("company_info", {})
                    pe = _parse_period_end(ci.get("period_end")) or date.today()
                    slug = label.lower().replace(" ", "-")
                    fid_bank = _get_or_create_bank(db, ent_name)
                    trust = _get_or_create_trust(db, ci.get("name") or label, fid_bank.id, slug, url)
                    _upsert_trust_data(db, trust.id, pe, fields)
                    db.commit()
                    trusts_done += 1
            except Exception as e:  # noqa: BLE001 — one bad PDF must not abort the run
                db.rollback()
                logger.exception("Fallo procesando %s · %s", ent_name, label)
                errors.append(f"{ent_name} · {label}: {e}")

        # Score the fiduciary entity periods (reuses the existing rating pipeline).
        _write_status(db, phase="calificando", processed=total, current=None)
        ratings = 0
        for pe in sorted(scored_periods):
            try:
                res = score_period(db, pe)
                ratings += res.get("scored", 0)
            except Exception as e:  # noqa: BLE001
                errors.append(f"scoring {pe}: {e}")

        result = {
            "entities_ingested": entities_done,
            "trusts_ingested": trusts_done,
            "periods_scored": len(scored_periods),
            "ratings_written": ratings,
            "errors": errors,
        }
        _write_status(db, is_running=False, phase="completado", processed=total,
                      last_sync=datetime.now(timezone.utc).isoformat(), result=result, error=None)
        return result
    except Exception as e:  # noqa: BLE001
        db.rollback()
        friendly = _friendly_error(e)
        logger.exception("run_fiduciaria_sync falló")
        _write_status(db, is_running=False, phase="error", error=friendly)
        return {"error": friendly, "errors": errors}
    finally:
        db.close()


def _parse_period_end(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def start_fiduciaria_sync_background(include_trusts: bool = True, only_latest: bool = False) -> Dict:
    """Kick off the sync in a daemon thread; returns immediately."""
    db = SessionLocal()
    try:
        st = get_fiduciaria_status(db)
        if st.get("is_running"):
            return {"started": False, "reason": "Ya hay una sincronización de fiduciarias en curso."}
    finally:
        db.close()

    def _run():
        with _lock:
            run_fiduciaria_sync(include_trusts=include_trusts, only_latest=only_latest)

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}
