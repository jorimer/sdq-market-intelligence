"""Frescura de las decisiones de TPM: avisa si no aparece un comunicado nuevo a tiempo.

Se registra en el auditor compartido (``data-freshness-audit``) vía
:func:`shared.operations.freshness.register_freshness_audit`. La operación
``bcrd-comunicados-sync`` puede correr "ok" sin traer nada nuevo; este chequeo mira la
antigüedad de la ÚLTIMA decisión ingerida (por su fecha) contra la cadencia ~mensual de
la Junta Monetaria. Advisory + dedup — el sistema avisa, el humano verifica.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from modules.macro_monitor.comunicados.service import latest_comunicado
from shared.notifications.service import notification_service
from shared.operations.freshness import (
    _clear_notified,
    _mark_notified,
    _recently_notified,
    register_freshness_audit,
)

logger = logging.getLogger("sdq.comunicados.freshness")

# La Junta Monetaria decide ~mensual; avisar si no hay decisión nueva en ~45 días (margen
# para un mes tardío). Re-notifica ~mensual (reusa el dedup de _recently_notified).
_MAX_AGE_DAYS = 45
_RENOTIFY_HOURS = 24 * 30
_KEY = "comunicados_tpm"


def audit_comunicados_freshness(db: Session, admin_ids: List[str], now: datetime) -> List[str]:
    """Avisa si la última decisión de TPM ingerida está más vieja que la cadencia mensual."""
    row = latest_comunicado(db)
    if row is None or not row.decision_date:
        return []  # nunca ingerido → lo cubre la frescura de la operación
    try:
        last = datetime.strptime(row.decision_date, "%Y-%m-%d")
    except ValueError:
        return []

    age_days = (now - last).days
    if age_days <= _MAX_AGE_DAYS:
        _clear_notified(db, _KEY)
        return []
    if _recently_notified(db, _KEY, _RENOTIFY_HOURS):
        return []

    title = "Decisión de TPM por verificar"
    body = (f"La última decisión de política monetaria del BCRD ingerida es del "
            f"{row.decision_date} (~{age_days} días). La Junta Monetaria decide cada ~mes; "
            f"conviene verificar si hay un comunicado nuevo sin capturar.")
    try:
        for uid in admin_ids:
            notification_service.create(db, user_id=uid, type="warning", title=title, body=body)
        _mark_notified(db, _KEY)
        return [_KEY]
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("no se pudo avisar la frescura de comunicados: %s", e)
        return []


register_freshness_audit(audit_comunicados_freshness)
