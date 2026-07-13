from datetime import datetime, timezone
from typing import Callable, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from shared.auth.jwt_handler import decode_token
from shared.auth.models import User, UserRole, role_satisfies
from shared.database.session import get_db

# auto_error=False: sin header Authorization NO se corta con 403 — se intenta la
# cookie httpOnly (brecha 2 del DD: la SPA autentica por cookie; los scripts/clientes
# de API siguen usando Bearer). Ambas fuentes llevan el MISMO access token JWT.
security = HTTPBearer(auto_error=False)

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency to extract and validate the current user from JWT.
    Fuentes del token, en orden: header ``Authorization: Bearer`` → cookie httpOnly."""
    token = credentials.credentials if credentials else request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token inválido",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin identificador de usuario",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado",
        )
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta bloqueada temporalmente por intentos fallidos",
        )

    return user


def require_role(*roles: UserRole) -> Callable:
    """Dependency que exige uno de `roles` — JERÁRQUICO: un rol superior satisface el
    requerimiento de uno inferior (p.ej. super_admin cumple cualquier exigencia de
    admin). Así agregar super_admin no deja afuera de lo que hoy pide `require_role(admin)`."""

    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not any(role_satisfies(current_user.role, r) for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol: {', '.join(r.value for r in roles)}",
            )
        return current_user

    return role_checker
