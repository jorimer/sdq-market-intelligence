"""Auditoría de frescura de datos — alerta de "dato viejo".

Operación de consola (agendable, diaria): para cada fuente recurrente compara su
última sincronización EXITOSA contra su cadencia; si se pasó (con margen), o nunca
corrió, notifica a los administradores (buzón in-app). Deduplica para no repetir el
mismo aviso a diario: re-notifica solo si pasó otra cadencia o si la fuente se puso
al día y volvió a atrasarse.

Cross-módulo por diseño (revisa TODAS las operaciones del registro); vive en el
framework de operaciones, no en un módulo de sector.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from shared.auth.models import User, UserRole
from shared.database.session import SessionLocal
from shared.notifications.service import notification_service
from shared.operations.models import OperationRun
from shared.operations.service import (
    OPERATIONS,
    Operation,
    get_schedules,
    register_operation,
)
from shared.settings.models import AppSetting

logger = logging.getLogger("sdq.operations.freshness")

FRESHNESS_OP_NAME = "data-freshness-audit"
# Margen sobre la cadencia antes de marcar "viejo" (evita falsos positivos por un
# pequeño retraso de publicación de la fuente).
_GRACE = 1.5

# Umbral de antigüedad de la ÚLTIMA ACCIÓN de rating soberano (ancla S&P) antes de
# PROPONER verificación. Las agencias suelen actuar/afirmar dentro de ~2 años; una acción
# más vieja no significa que la nota cambió, pero sí que el dato declarado debe re-verificarse
# (este fue el síntoma que se pudrió con RD). El sistema propone; el humano dispone (nunca
# sobrescribe una nota por su cuenta).
_SOVEREIGN_MAX_AGE_MONTHS = 24
# Cadencia de re-propuesta del aviso soberano (~mensual), reusa el dedupe de _recently_notified.
_SOVEREIGN_RENOTIFY_HOURS = 24 * 30

# Cadencia de publicación esperada de cada informe recurrente del BCRD → horas. Si la
# ÚLTIMA edición ingerida con éxito supera esta cadencia (con margen _GRACE), se AVISA
# que no ha aparecido una edición nueva a tiempo — puede ser un atraso de la fuente o un
# cambio de formato/URL en el CDN (el síntoma que dejó caída la ingesta del IPoM: el BCRD
# renombró el archivo y el sync corría "ok" sin traer nada nuevo). Advisory: el sistema
# avisa, el humano verifica. La frescura se mide por antigüedad de la ingestión (created_at),
# que solo avanza con una edición nueva — así distingue "el sync corre en vacío" de "entró algo".
_PUBLICATION_CADENCE_HOURS = {
    "trimestral": 24 * 90,
    "semestral": 24 * 182,
    "anual": 24 * 365,
}


def _now_naive() -> datetime:
    """UTC naive (las columnas DateTime son naive: Postgres TIMESTAMP s/ TZ + SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alert_key(op: str) -> str:
    return f"freshness_alert:{op}"


def _last_success(db: Session, op_name: str) -> Optional[datetime]:
    """Fin de la última corrida EXITOSA de *op_name*, o None si nunca completó."""
    row = (
        db.query(OperationRun)
        .filter(OperationRun.operation == op_name, OperationRun.status == "completed")
        .order_by(OperationRun.finished_at.desc().nullslast())
        .first()
    )
    return row.finished_at if row else None


def _recently_notified(db: Session, op_name: str, interval_hours: int) -> bool:
    """¿Ya se avisó por esta fuente dentro de su última cadencia? (anti-spam)."""
    row = db.query(AppSetting).filter(AppSetting.key == _alert_key(op_name)).first()
    if not row or not row.value:
        return False
    try:
        last = datetime.fromisoformat(row.value)
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - last).total_seconds() < interval_hours * 3600


def _mark_notified(db: Session, op_name: str) -> None:
    key = _alert_key(op_name)
    now_iso = datetime.now(timezone.utc).isoformat()
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = now_iso
        row.is_secret = False
    else:
        db.add(AppSetting(key=key, value=now_iso, is_secret=False))
    db.commit()


def _clear_notified(db: Session, op_name: str) -> None:
    """La fuente volvió a estar al día → limpiar el marcador para re-avisar si recae."""
    row = db.query(AppSetting).filter(AppSetting.key == _alert_key(op_name)).first()
    if row:
        db.delete(row)
        db.commit()


def _admin_ids(db: Session) -> List[str]:
    """IDs de usuarios activos con rol admin o super_admin (destinatarios de la alerta)."""
    rows = (
        db.query(User)
        .filter(User.is_active.is_(True),
                User.role.in_([UserRole.admin, UserRole.super_admin]))
        .all()
    )
    return [u.id for u in rows]


def _audit_sovereign_ratings(db: Session, admin_ids: List[str], now: datetime) -> List[str]:
    """PROPONE (no sobrescribe) la re-verificación de un rating soberano cuya última acción
    del ancla (S&P) supera :data:`_SOVEREIGN_MAX_AGE_MONTHS`. El store de ratings no tiene
    OperationRun propio, así que su frescura se mide por la ANTIGÜEDAD DEL DATO (action_date),
    no por la cadencia de un sync. Deduplica por país (~mensual). Devuelve los ISO propuestos."""
    from shared.contracts.sovereign_ratings import (
        AGENCY_NAMES, ANCHOR_AGENCY, overdue_ratings)

    proposed: List[str] = []
    try:
        stale = overdue_ratings(db, _SOVEREIGN_MAX_AGE_MONTHS, today=now.date())
    except Exception as e:  # noqa: BLE001 — la auditoría soberana no debe abortar el resto
        logger.warning("no se pudo auditar el rating soberano: %s", e)
        return proposed

    for s in stale:
        key = f"sovereign:{s['iso']}"
        if _recently_notified(db, key, _SOVEREIGN_RENOTIFY_HOURS):
            continue
        years = s["age_months"] / 12
        title = f"Rating soberano por verificar: {s['iso']}"
        body = (f"La calificación {AGENCY_NAMES.get(ANCHOR_AGENCY, 'S&P')} de {s['iso']} "
                f"({s['rating']}) tiene su última acción del {s['action_date']} "
                f"(~{years:.1f} años). Verificar que siga vigente y, si aplica, anotar la "
                f"fecha de afirmación. El sistema no sobrescribe la nota por su cuenta.")
        try:
            for uid in admin_ids:
                notification_service.create(db, user_id=uid, type="warning",
                                            title=title, body=body)
            _mark_notified(db, key)
            proposed.append(s["iso"])
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning("no se pudo proponer la frescura soberana de %s: %s", s["iso"], e)
    return proposed


def _audit_publications(db: Session, admin_ids: List[str], now: datetime) -> List[str]:
    """AVISA (advisory) cuando la última edición ingerida de una publicación recurrente del
    BCRD supera su cadencia esperada: no apareció una edición nueva a tiempo. Mide la frescura
    por la antigüedad de la ÚLTIMA INGESTIÓN EXITOSA (``created_at``), que solo avanza con una
    edición nueva — así distingue "el sync corre en vacío" (renombrado del CDN) de "entró algo
    nuevo". No avisa las nunca-ingeridas (eso ya lo cubre la frescura de la operación). Deduplica
    por informe (reusa el buzón de _recently_notified). Devuelve las report_keys avisadas."""
    from shared.publications import catalog as pub_catalog
    from shared.publications.models import Publication

    alerted: List[str] = []
    try:
        for key in pub_catalog.report_keys("BCRD"):
            spec = pub_catalog.REPORTS[key]
            max_age_h = _PUBLICATION_CADENCE_HOURS.get(spec.cadence)
            if max_age_h is None:
                continue  # cadencia irregular/puntual → sin frescura esperada
            akey = f"publication:{key}"
            last = (
                db.query(Publication.created_at)
                .filter(Publication.report_key == key, Publication.status == "ok")
                .order_by(Publication.created_at.desc().nullslast())
                .first()
            )
            if last is None or last[0] is None:
                continue  # nunca ingerida con éxito → lo cubre la frescura de la operación
            age_h = (now - last[0]).total_seconds() / 3600
            if age_h <= max_age_h * _GRACE:
                _clear_notified(db, akey)
                continue
            if _recently_notified(db, akey, max_age_h):
                continue
            days = int(age_h // 24)
            title = f"Publicación por verificar: {spec.name}"
            body = (f"La última edición ingerida de «{spec.name}» tiene ~{days} día(s); no ha "
                    f"aparecido una edición nueva dentro de su cadencia ({spec.cadence}). Puede "
                    f"ser un atraso de la fuente o un cambio de formato/URL en el CDN del BCRD; "
                    f"conviene verificar la disponibilidad de una edición más reciente.")
            try:
                for uid in admin_ids:
                    notification_service.create(db, user_id=uid, type="warning",
                                                title=title, body=body)
                _mark_notified(db, akey)
                alerted.append(key)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                logger.warning("no se pudo avisar la frescura de la publicación %s: %s", key, e)
    except Exception as e:  # noqa: BLE001 — la auditoría de publicaciones no debe abortar el resto
        logger.warning("no se pudo auditar la frescura de publicaciones: %s", e)
    return alerted


def run_freshness_audit(db: Session) -> Dict:
    """Audita la frescura de cada fuente recurrente y notifica las atrasadas.

    Devuelve ``{checked, n_overdue, overdue, notified, sovereign_proposed, publications_stale}``.
    Solo considera operaciones con cadencia (>0) que no necesitan parámetros (las on-demand no
    tienen frescura esperada). No se audita a sí misma. Además: propone re-verificar ratings
    soberanos cuya última acción envejeció (dato declarado, no un sync agendado), y avisa las
    publicaciones BCRD sin edición nueva dentro de su cadencia (renombrado/atraso del CDN).
    """
    scheds = get_schedules(db)
    admin_ids = _admin_ids(db)
    now = _now_naive()
    checked = 0
    overdue: List[str] = []
    notified = 0

    for name, op in OPERATIONS.items():
        if name == FRESHNESS_OP_NAME:
            continue
        if op.default_interval_hours <= 0 or op.needs_params:
            continue  # on-demand / parametrizada → sin frescura esperada
        sched = scheds.get(name) or {}
        interval = sched.get("interval_hours") or op.default_interval_hours
        checked += 1

        last = _last_success(db, name)
        if last is not None:
            elapsed_h = (now - last).total_seconds() / 3600
            is_overdue = elapsed_h > interval * _GRACE
        else:
            elapsed_h = None
            is_overdue = True  # nunca sincronizó

        if not is_overdue:
            _clear_notified(db, name)
            continue

        overdue.append(name)
        if _recently_notified(db, name, interval):
            continue

        title = f"Dato desactualizado: {op.label}"
        if elapsed_h is None:
            body = (f"La fuente «{op.label}» nunca se sincronizó con éxito. "
                    f"Cadencia esperada: cada {interval} h.")
        else:
            days = int(elapsed_h // 24)
            body = (f"«{op.label}» no se actualiza hace ~{days} día(s) "
                    f"(cadencia esperada: cada {interval} h).")
        # Aislado por fuente: una falla al notificar (p.ej. un transitorio de DB) no debe
        # abortar la auditoría de las demás ni dejar avisos a medias sin marcar (re-spam).
        try:
            for uid in admin_ids:
                notification_service.create(db, user_id=uid, type="warning", title=title, body=body)
            _mark_notified(db, name)
            notified += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning("no se pudo notificar la frescura de %s: %s", name, e)

    sovereign_proposed = _audit_sovereign_ratings(db, admin_ids, now)
    publications_stale = _audit_publications(db, admin_ids, now)

    return {"checked": checked, "n_overdue": len(overdue),
            "overdue": overdue, "notified": notified,
            "sovereign_proposed": sovereign_proposed,
            "publications_stale": publications_stale}


def _run(params, user_id, set_phase) -> Dict:
    db = SessionLocal()
    try:
        set_phase("auditando frescura de las fuentes de datos")
        return run_freshness_audit(db)
    finally:
        db.close()


register_operation(Operation(
    name=FRESHNESS_OP_NAME,
    label="Auditoría de frescura de datos",
    description="Revisa cada fuente: si su última sincronización exitosa se pasó de su "
                "cadencia (o nunca corrió), notifica a los administradores. Agendable "
                "(recomendada diaria).",
    runner=_run,
    default_interval_hours=24,
))
