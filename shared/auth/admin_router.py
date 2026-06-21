"""Administración de usuarios (RBAC) — CRUD gateado por rol con barandas de seguridad.

Prefijo: /api/v1/admin/users. Acceso: admin+ (super_admin lo cumple por jerarquía).

Barandas (anti-escalada / anti-lockout):
  - Un actor solo administra usuarios de rol INFERIOR (super_admin administra a todos,
    incl. otros admins/super_admins).
  - admin NO puede crear ni elevar a admin/super_admin; solo super_admin asigna esos roles.
  - Nadie cambia su propio rol ni se desactiva/elimina a sí mismo.
  - No se puede degradar/desactivar/eliminar al ÚLTIMO super_admin activo.
  - Eliminar (hard delete) es exclusivo de super_admin; admin usa desactivar.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.jwt_handler import hash_password
from shared.auth.models import AccessTier, ROLE_RANK, User, UserRole
from shared.database.session import get_db

logger = logging.getLogger("sdq.auth.admin")
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────
class AdminUserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tier: str
    is_active: bool
    created_at: Optional[str] = None


class CreateUserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    role: UserRole = UserRole.viewer
    tier: AccessTier = AccessTier.free


class UpdateUserIn(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    tier: Optional[AccessTier] = None
    is_active: Optional[bool] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8)


# ── Guards ────────────────────────────────────────────────────────
def _can_manage(actor: User, target_role: UserRole) -> bool:
    """El actor puede administrar a un usuario de rol `target_role`.
    Fail-closed: rol desconocido del actor → rank mínimo; del target → rank máximo."""
    if actor.role == UserRole.super_admin:
        return True
    return ROLE_RANK.get(actor.role, -1) > ROLE_RANK.get(target_role, 99)


def _can_assign_role(actor: User, new_role: UserRole) -> bool:
    """Qué roles puede OTORGAR el actor (anti-escalada). Fail-closed ante rol futuro
    sin rank: un rol desconocido se trata como el más alto → no asignable por admin."""
    if actor.role == UserRole.super_admin:
        return True
    # admin solo puede asignar roles por debajo de admin.
    return ROLE_RANK.get(new_role, 99) < ROLE_RANK[UserRole.admin]


def _is_last_active_super_admin(db: Session, target: User) -> bool:
    if target.role != UserRole.super_admin or not target.is_active:
        return False
    others = (
        db.query(User)
        .filter(User.role == UserRole.super_admin, User.is_active.is_(True),
                User.id != target.id)
        .count()
    )
    return others == 0


def _out(u: User) -> AdminUserOut:
    return AdminUserOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role.value,
        tier=u.tier.value if u.tier else AccessTier.free.value,
        is_active=u.is_active,
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


def _get_target(db: Session, user_id: str) -> User:
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return u


# ── Endpoints ─────────────────────────────────────────────────────
@router.get("", response_model=List[AdminUserOut], summary="Listar usuarios (admin+)")
async def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    rows = db.query(User).order_by(User.created_at.desc()).all()
    return [_out(u) for u in rows]


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED,
             summary="Crear usuario (admin+)")
async def create_user(
    body: CreateUserIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(UserRole.admin)),
):
    if not _can_assign_role(actor, body.role):
        raise HTTPException(status_code=403,
                            detail="No tenés permiso para asignar ese rol.")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="El email ya está registrado")
    u = User(
        email=body.email, password_hash=hash_password(body.password),
        full_name=body.full_name, role=body.role, tier=body.tier,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    logger.info("admin %s creó usuario %s (rol=%s)", actor.email, u.email, u.role.value)
    return _out(u)


@router.patch("/{user_id}", response_model=AdminUserOut, summary="Editar usuario (admin+)")
async def update_user(
    user_id: str,
    body: UpdateUserIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(UserRole.admin)),
):
    target = _get_target(db, user_id)
    is_self = target.id == actor.id

    # El actor debe poder administrar el rol ACTUAL del target.
    if not _can_manage(actor, target.role):
        raise HTTPException(status_code=403,
                            detail="No podés administrar usuarios de rol igual o superior.")

    if body.role is not None and body.role != target.role:
        if is_self:
            raise HTTPException(status_code=403, detail="No podés cambiar tu propio rol.")
        if not _can_assign_role(actor, body.role):
            raise HTTPException(status_code=403,
                                detail="No tenés permiso para asignar ese rol.")
        # No degradar al último super_admin activo.
        if target.role == UserRole.super_admin and body.role != UserRole.super_admin \
                and _is_last_active_super_admin(db, target):
            raise HTTPException(status_code=409,
                                detail="No se puede degradar al último super_admin activo.")
        target.role = body.role

    if body.is_active is not None and body.is_active != target.is_active:
        if is_self and not body.is_active:
            raise HTTPException(status_code=403, detail="No podés desactivarte a vos mismo.")
        if not body.is_active and _is_last_active_super_admin(db, target):
            raise HTTPException(status_code=409,
                                detail="No se puede desactivar al último super_admin activo.")
        target.is_active = body.is_active
        if body.is_active:
            target.failed_login_attempts = 0
            target.locked_until = None

    if body.full_name is not None:
        target.full_name = body.full_name
    if body.tier is not None:
        target.tier = body.tier

    db.commit()
    db.refresh(target)
    logger.info("admin %s editó usuario %s", actor.email, target.email)
    return _out(target)


@router.post("/{user_id}/reset-password", summary="Resetear contraseña (admin+)")
async def reset_password(
    user_id: str,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(UserRole.admin)),
):
    target = _get_target(db, user_id)
    if not _can_manage(actor, target.role) and target.id != actor.id:
        raise HTTPException(status_code=403,
                            detail="No podés administrar usuarios de rol igual o superior.")
    target.password_hash = hash_password(body.new_password)
    target.failed_login_attempts = 0
    target.locked_until = None
    db.commit()
    logger.info("admin %s reseteó contraseña de %s", actor.email, target.email)
    return {"ok": True}


@router.delete("/{user_id}", summary="Eliminar usuario (solo super_admin)")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(UserRole.super_admin)),
):
    target = _get_target(db, user_id)
    if target.id == actor.id:
        raise HTTPException(status_code=403, detail="No podés eliminarte a vos mismo.")
    if _is_last_active_super_admin(db, target):
        raise HTTPException(status_code=409,
                            detail="No se puede eliminar al último super_admin activo.")
    db.delete(target)
    db.commit()
    logger.info("super_admin %s eliminó usuario %s", actor.email, target.email)
    return {"ok": True}
