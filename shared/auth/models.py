import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String

from shared.database.base import Base, UUIDMixin


class UserRole(str, enum.Enum):
    """Rol = qué puede ADMINISTRAR el usuario en la plataforma. Jerárquico:
    super_admin ⊇ admin ⊇ analyst ⊇ viewer (ver ROLE_RANK / role_satisfies)."""
    super_admin = "super_admin"
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class AccessTier(str, enum.Enum):
    """Tier = nivel de ACCESO a contenido, eje independiente del rol (monetización).
    Declarado para habilitar planes pagos a futuro; hoy no restringe contenido."""
    free = "free"
    pro = "pro"
    enterprise = "enterprise"


# Jerarquía de roles: número mayor = más privilegio. Un rol "satisface" un
# requerimiento si su rank es >= al del rol requerido (super_admin pasa todo).
ROLE_RANK = {
    UserRole.viewer: 0,
    UserRole.analyst: 1,
    UserRole.admin: 2,
    UserRole.super_admin: 3,
}


def role_satisfies(user_role: UserRole, required: UserRole) -> bool:
    """¿`user_role` cumple (es >= que) el rol `required`?"""
    return ROLE_RANK.get(user_role, -1) >= ROLE_RANK.get(required, 99)


class User(UUIDMixin, Base):
    __tablename__ = "users"

    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.viewer, nullable=False)
    # Nivel de acceso (monetización) — independiente del rol administrativo.
    tier = Column(Enum(AccessTier, name="access_tier"), default=AccessTier.free,
                  server_default=AccessTier.free.value, nullable=False)
    organization_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
