import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from shared.auth.dependencies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    get_current_user,
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
)
from shared.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from shared.auth.models import User, UserRole
from shared.config.settings import settings
from shared.database.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Cookies httpOnly (brecha 2 del DD): la SPA ya no persiste tokens en localStorage —
# el navegador guarda ambos tokens en cookies que el JS no puede leer (mitiga robo por
# XSS). SameSite=Lax evita que un POST cross-site arrastre la sesión (CSRF). Los tokens
# SIGUEN viajando en el body para clientes de API por header Bearer (scripts, curl);
# el header y la cookie son fuentes equivalentes en get_current_user.
_REFRESH_COOKIE_PATH = "/api/v1/auth"  # el refresh token solo viaja a /auth/*


def _cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "secure": settings.ENVIRONMENT == "production",
        "samesite": "lax",
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE, access_token, path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **_cookie_kwargs())
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, path=_REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, **_cookie_kwargs())


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", **_cookie_kwargs())
    response.delete_cookie(REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH, **_cookie_kwargs())


def _tier_value(user: User) -> str:
    """tier nunca debería ser None (server_default 'free'), pero el path de login no
    debe reventar (500) por una fila legada sin tier."""
    return user.tier.value if user.tier else "free"


# --- Schemas ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    # NOTE: role is intentionally NOT accepted here — public registration always
    # creates a 'viewer'. Role elevation is server-side only (bootstrap/admin).


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    full_name: str
    role: str
    tier: str


class RefreshRequest(BaseModel):
    # Opcional: la SPA refresca vía cookie httpOnly (body vacío); los clientes de API
    # pueden seguir mandando el token en el body.
    refresh_token: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tier: str
    is_active: bool


# --- Endpoints ---

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """Registrar un nuevo usuario."""
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está registrado",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=UserRole.viewer,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("User registered: %s", user.email)

    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    refresh_token = create_refresh_token({"sub": user.id})
    set_auth_cookies(response, access_token, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        tier=_tier_value(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Iniciar sesión."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    # Check lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta bloqueada temporalmente. Intente de nuevo más tarde.",
        )

    if not verify_password(body.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            logger.warning("Account locked: %s", user.email)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    # Reset failed attempts on successful login
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    logger.info("User logged in: %s", user.email)

    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    refresh_token = create_refresh_token({"sub": user.id})
    set_auth_cookies(response, access_token, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        tier=_tier_value(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response,
                  body: Optional[RefreshRequest] = None, db: Session = Depends(get_db)):
    """Refrescar access token usando refresh token (cookie httpOnly o body)."""
    token = (body.refresh_token if body and body.refresh_token
             else request.cookies.get(REFRESH_COOKIE))
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token requerido (cookie o body)",
        )
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token inválido",
        )

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado",
        )

    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    new_refresh_token = create_refresh_token({"sub": user.id})
    set_auth_cookies(response, access_token, new_refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        tier=_tier_value(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    """Cerrar sesión: borra las cookies httpOnly (el JS no puede hacerlo)."""
    clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Obtener información del usuario autenticado."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        tier=_tier_value(current_user),
        is_active=current_user.is_active,
    )
