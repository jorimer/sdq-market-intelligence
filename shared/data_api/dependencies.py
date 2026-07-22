"""Autenticación por llave de la Data API + resolución de alcance.

Eje independiente del auth de la SPA: aquí NO se acepta ni JWT ni cookie. Una llave es
lo único que autentica a un consumidor máquina-a-máquina, y un usuario logueado en la
web no puede usar su sesión para saltarse la cuota de API.

El **alcance** no se declara en la llave: se resuelve contra los entitlements del usuario
dueño con el mismo ``can_access`` que gobierna la web (``shared/products/access``). Así
otorgar y revocar acceso es una sola operación y los dos canales no pueden divergir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from shared.auth.models import User
from shared.data_api import keys as key_utils
from shared.data_api.models import ApiKey
from shared.data_api.quota import QuotaState, check_quota, record_usage
from shared.database.session import get_db
from shared.products.access import AccessOutcome, can_access
from shared.products.tiers import ProductTier

# auto_error=False: el 401 lo emitimos nosotros, bilingüe y con el mismo cuerpo que el
# resto de los errores de esta API (un cliente máquina parsea el cuerpo, no el texto).
bearer = HTTPBearer(auto_error=False)

# Nivel comercial que se exige para leer los ACTIVOS DE DATOS de un sector. Pulse es el
# piso publicado del sector: si el sector está publicado y el cliente alcanza su nivel de
# entrada, puede leer sus series y derivados. La narrativa —lo que NO va por API— vive en
# Insight/Deep Dive, así que esto no regala el producto de reporte.
DATA_ACCESS_TIER = ProductTier.pulse


def api_error(status_code: int, code: str, es: str, en: str, **extra) -> HTTPException:
    """Error de la Data API: bilingüe y con código estable para el cliente.

    Excepción deliberada a la convención del repo (errores en español): el consumidor es
    un sistema de terceros que puede no ser dominicano. El ``code`` es lo que un cliente
    debe programar contra — el texto puede cambiar, el código no.
    """
    detail = {"code": code, "message": es, "message_en": en}
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


@dataclass
class ApiContext:
    """Todo lo que un handler necesita: quién llama, qué puede ver, cuánto le queda."""

    key: ApiKey
    user: User
    quota: QuotaState
    db: Session

    @property
    def allows_restricted_sources(self) -> bool:
        """¿Esta llave puede recibir dato verbatim de una fuente con licencia
        no-comercial / share-alike? Solo si su uso declarado es interno (insumo de
        análisis propio), nunca por default."""
        return str(self.key.usage or "external") == "internal"

    def can_read_sector(self, sector_key: str) -> bool:
        decision = can_access(self.db, self.user, sector_key, DATA_ACCESS_TIER)
        return decision.outcome is AccessOutcome.allowed

    def meta(self) -> dict:
        """Sobre ``meta`` común a toda respuesta."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "client_ref": self.key.client_ref,
            "usage": self.key.usage,
            "quota": {
                "limit_per_minute": self.quota.limit_per_minute,
                "quota_per_month": self.quota.quota_per_month,
                "used_this_period": self.quota.used_this_period,
                "remaining_this_period": self.quota.remaining_this_period,
            },
            "license": (
                "Uso interno del titular de la llave. Prohibida la redistribución y la "
                "reventa. Al citar, atribuir a SDQ Market Intelligence y a la fuente "
                "primaria declarada en cada activo."
            ),
        }


def _load_key(db: Session, token: str) -> ApiKey:
    parsed = key_utils.parse_token(token)
    if parsed is None:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "invalid_key",
            "Llave de API inválida o mal formada.",
            "Invalid or malformed API key.",
        )
    _env, prefix, secret = parsed
    key = db.query(ApiKey).filter(ApiKey.prefix == prefix).one_or_none()
    # Mismo error para "no existe" y "secreto incorrecto": distinguirlos le confirmaría
    # a un atacante que un prefijo es real.
    if key is None or not key_utils.verify_secret(secret, str(key.secret_hash)):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "invalid_key",
            "Llave de API inválida o mal formada.",
            "Invalid or malformed API key.",
        )
    if not key.active or key.revoked_at is not None:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "key_revoked",
            "La llave fue revocada.", "The API key has been revoked.",
        )
    if key.expires_at is not None and key.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "key_expired",
            "La llave está vencida.", "The API key has expired.",
        )
    return key


async def require_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> ApiContext:
    """Autentica la llave, verifica al dueño y aplica la cuota. 401 · 403 · 429."""
    token = credentials.credentials if credentials else request.headers.get("X-API-Key", "")
    if not token:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "missing_key",
            "Falta la llave de API (header Authorization: Bearer o X-API-Key).",
            "Missing API key (Authorization: Bearer header or X-API-Key).",
        )

    key = _load_key(db, token)
    user = db.query(User).filter(User.id == key.user_id).one_or_none()
    if user is None or not user.is_active:
        raise api_error(
            status.HTTP_403_FORBIDDEN, "owner_inactive",
            "La cuenta dueña de la llave está desactivada.",
            "The account owning this key is inactive.",
        )

    quota = check_quota(db, key)
    if not quota.allowed:
        # El rechazo también se audita y también consume cuota: si no lo hiciera, un
        # cliente mal configurado podría martillar gratis para siempre.
        record_usage(
            db, key, resource=request.url.path.rsplit("/", 1)[-1] or "unknown",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": quota.reason,
                "message": ("Se agotó la cuota mensual de la llave."
                            if quota.reason == "quota_exhausted"
                            else "Se excedió el límite de llamadas por minuto."),
                "message_en": ("Monthly quota exhausted for this key."
                               if quota.reason == "quota_exhausted"
                               else "Per-minute rate limit exceeded."),
                "retry_after_seconds": quota.retry_after_seconds,
            },
            headers={"Retry-After": str(quota.retry_after_seconds)},
        )

    return ApiContext(key=key, user=user, quota=quota, db=db)
