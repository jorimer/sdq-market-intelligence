"""Cuota mensual y rate limit por llave + bitácora de uso.

Se cuenta sobre ``data_api_usage`` (la misma tabla que audita), no sobre un contador en
memoria: el backend corre en más de un proceso y un contador local dejaría la cuota
efectiva multiplicada por el número de workers. El costo es un ``COUNT`` indexado por
llamada, aceptable en este orden de magnitud; si dejara de serlo, el reemplazo natural
es Redis, no un contador local.

Excederse devuelve 429 con ``Retry-After``. Nunca se sirve un payload truncado ni
degradado en silencio: un cliente que automatiza no puede distinguir "no hay dato" de
"te corté por cuota", y esa confusión termina en un informe con un hueco inexplicado.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from shared.data_api.models import ApiKey, ApiUsage

RATE_WINDOW_SECONDS = 60


def quota_period(moment: Optional[datetime] = None) -> str:
    """Período de cuota "YYYY-MM" en UTC."""
    m = moment or datetime.now(timezone.utc)
    return f"{m.year:04d}-{m.month:02d}"


@dataclass(frozen=True)
class QuotaState:
    """Estado de consumo de una llave, para decidir y para informar en ``meta``."""

    allowed: bool
    reason: str = ""                       # "rate_limit" | "quota_exhausted"
    retry_after_seconds: int = 0
    used_this_minute: int = 0
    used_this_period: int = 0
    limit_per_minute: int = 0
    quota_per_month: Optional[int] = None

    @property
    def remaining_this_period(self) -> Optional[int]:
        if self.quota_per_month is None:
            return None
        return max(0, self.quota_per_month - self.used_this_period)


def check_quota(db: Session, key: ApiKey, *, now: Optional[datetime] = None) -> QuotaState:
    """¿Puede esta llave hacer una llamada más? No escribe nada."""
    moment = now or datetime.now(timezone.utc)
    naive_now = moment.replace(tzinfo=None)
    window_start = naive_now - timedelta(seconds=RATE_WINDOW_SECONDS)
    period = quota_period(moment)

    per_minute = int(key.rate_limit_per_minute or 0)
    monthly = key.quota_per_month

    used_minute = (
        db.query(ApiUsage)
        .filter(ApiUsage.api_key_id == key.id, ApiUsage.requested_at >= window_start)
        .count()
    )
    used_period = (
        db.query(ApiUsage)
        .filter(ApiUsage.api_key_id == key.id, ApiUsage.quota_period == period)
        .count()
    )

    if per_minute > 0 and used_minute >= per_minute:
        return QuotaState(
            allowed=False, reason="rate_limit", retry_after_seconds=RATE_WINDOW_SECONDS,
            used_this_minute=used_minute, used_this_period=used_period,
            limit_per_minute=per_minute, quota_per_month=monthly,
        )
    if monthly is not None and used_period >= int(monthly):
        return QuotaState(
            allowed=False, reason="quota_exhausted",
            retry_after_seconds=_seconds_to_next_period(moment),
            used_this_minute=used_minute, used_this_period=used_period,
            limit_per_minute=per_minute, quota_per_month=monthly,
        )
    return QuotaState(
        allowed=True, used_this_minute=used_minute, used_this_period=used_period,
        limit_per_minute=per_minute, quota_per_month=monthly,
    )


def _seconds_to_next_period(moment: datetime) -> int:
    """Segundos hasta que la cuota mensual se renueve (1º del mes siguiente, UTC)."""
    year, month = moment.year, moment.month
    nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else \
        datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return max(1, int((nxt - moment).total_seconds()))


def record_usage(
    db: Session,
    key: ApiKey,
    *,
    resource: str,
    status_code: int,
    rows: int = 0,
    latency_ms: Optional[int] = None,
    asset_key: Optional[str] = None,
    as_of: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ApiUsage:
    """Registra la llamada — servida o rechazada — y actualiza ``last_used_at``.

    Que lo rechazado también cuente para la cuota es deliberado: si no contara, un
    cliente mal configurado podría martillar el endpoint gratis para siempre.
    """
    moment = now or datetime.now(timezone.utc)
    naive = moment.replace(tzinfo=None)
    row = ApiUsage(
        api_key_id=key.id, resource=resource, asset_key=asset_key,
        status_code=int(status_code), rows=int(rows or 0),
        latency_ms=int(latency_ms) if latency_ms is not None else None,
        as_of=as_of, requested_at=naive, quota_period=quota_period(moment),
    )
    db.add(row)
    key.last_used_at = naive
    db.commit()
    return row
