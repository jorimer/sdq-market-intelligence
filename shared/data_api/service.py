"""Alta, listado y revocación de llaves de la Data API.

El secreto se devuelve UNA sola vez, al crear. No hay "ver llave": si se pierde, se
revoca y se emite otra. Es lo correcto y además lo único posible — solo se guarda el
hash.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data_api.keys import KEY_ENV_LIVE, mint_key
from shared.data_api.models import ApiKey, ApiUsage
from shared.data_api.quota import quota_period


class ApiKeyError(ValueError):
    """Datos inválidos para crear o revocar una llave."""


# Uso declarado del consumidor — ver ``ApiKey.usage``. "internal" habilita recibir dato
# verbatim de fuentes con licencia no-comercial o share-alike; "external" no.
VALID_USAGE = ("internal", "external")


def _serialize(key: ApiKey, *, used_this_period: int = 0) -> Dict[str, Any]:
    return {
        "id": key.id,
        "user_id": key.user_id,
        "name": key.name,
        "prefix": key.prefix,
        "client_ref": key.client_ref,
        "usage": key.usage,
        "rate_limit_per_minute": key.rate_limit_per_minute,
        "quota_per_month": key.quota_per_month,
        "used_this_period": used_this_period,
        "active": bool(key.active),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "note": key.note,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


def create_key(
    db: Session,
    *,
    user_id: str,
    name: str,
    client_ref: Optional[str] = None,
    usage: str = "external",
    rate_limit_per_minute: int = 60,
    quota_per_month: Optional[int] = None,
    expires_at: Optional[datetime] = None,
    note: Optional[str] = None,
    env: str = KEY_ENV_LIVE,
) -> Dict[str, Any]:
    """Crea una llave. El ``token`` del resultado NO se puede recuperar después."""
    if not (name or "").strip():
        raise ApiKeyError("La llave necesita un nombre que identifique al consumidor.")
    if usage not in VALID_USAGE:
        raise ApiKeyError(
            f"Uso inválido '{usage}'. Use 'internal' (insumo de análisis propio, el dato "
            f"no sale hacia terceros) o 'external'.")
    if rate_limit_per_minute < 1:
        raise ApiKeyError("El límite por minuto debe ser al menos 1.")
    if quota_per_month is not None and quota_per_month < 1:
        raise ApiKeyError("La cuota mensual debe ser al menos 1, o vacía para no tener tope.")

    minted = mint_key(env)
    if expires_at is not None and expires_at.tzinfo is not None:
        # Columnas DateTime naive (parity SQLite↔Postgres), igual que en entitlements.
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)

    row = ApiKey(
        user_id=user_id, name=name.strip(), prefix=minted.prefix,
        secret_hash=minted.secret_hash, client_ref=(client_ref or "").strip() or None,
        usage=usage,
        rate_limit_per_minute=int(rate_limit_per_minute),
        quota_per_month=int(quota_per_month) if quota_per_month is not None else None,
        active=True, expires_at=expires_at, note=note,
    )
    db.add(row)
    db.commit()
    out = _serialize(row)
    out["token"] = minted.token
    out["token_note"] = (
        "Guarde este valor ahora: no se puede volver a mostrar. Si se pierde, revoque "
        "la llave y emita una nueva."
    )
    return out


def list_keys(db: Session, *, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q = db.query(ApiKey)
    if user_id:
        q = q.filter(ApiKey.user_id == user_id)
    rows = q.order_by(ApiKey.created_at.desc()).all()
    period = quota_period()
    out: List[Dict[str, Any]] = []
    for r in rows:
        used = (
            db.query(ApiUsage)
            .filter(ApiUsage.api_key_id == r.id, ApiUsage.quota_period == period)
            .count()
        )
        out.append(_serialize(r, used_this_period=used))
    return out


def revoke_key(db: Session, *, key_id: str, revoked_by: Optional[str]) -> Dict[str, Any]:
    row = db.query(ApiKey).filter(ApiKey.id == key_id).one_or_none()
    if row is None:
        raise ApiKeyError("La llave no existe.")
    row.active = False
    row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.revoked_by = revoked_by
    db.commit()
    return _serialize(row)


def usage_summary(db: Session, *, key_id: str, limit: int = 50) -> Dict[str, Any]:
    """Últimas llamadas de una llave + consumo del período (soporte y auditoría)."""
    period = quota_period()
    rows = (
        db.query(ApiUsage)
        .filter(ApiUsage.api_key_id == key_id)
        .order_by(ApiUsage.requested_at.desc())
        .limit(limit)
        .all()
    )
    used = (
        db.query(ApiUsage)
        .filter(ApiUsage.api_key_id == key_id, ApiUsage.quota_period == period)
        .count()
    )
    return {
        "key_id": key_id,
        "period": period,
        "used_this_period": used,
        "recent": [
            {
                "resource": r.resource, "asset_key": r.asset_key,
                "status_code": r.status_code, "rows": r.rows,
                "latency_ms": r.latency_ms, "as_of": r.as_of,
                "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            }
            for r in rows
        ],
    }
