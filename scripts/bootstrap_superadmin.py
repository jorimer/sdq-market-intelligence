"""Bootstrap del super_admin real desde variables de entorno (idempotente).

Crea el primer super_admin de la plataforma SOLO si no existe ninguno todavía.
Pensado para correr en el arranque del contenedor (start.sh), tras las migraciones.

Variables de entorno:
    SUPERADMIN_EMAIL      — email del super_admin (requerido para crear)
    SUPERADMIN_PASSWORD   — contraseña inicial (requerido para crear)
    SUPERADMIN_NAME       — nombre completo (opcional; default "Super Admin")

Comportamiento:
  - Si ya existe AL MENOS un super_admin → no hace nada (no toca contraseñas).
  - Si no existe ninguno y faltan las env vars → solo avisa y sale (no falla el deploy).
  - Si no existe ninguno y están las env vars:
      · si el email ya existe (otro rol) → lo ELEVA a super_admin (sin tocar su clave),
      · si no → lo crea con la clave provista.

    python scripts/bootstrap_superadmin.py
"""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.auth.jwt_handler import hash_password  # noqa: E402
from shared.auth.models import AccessTier, User, UserRole  # noqa: E402
from shared.database.session import SessionLocal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sdq.bootstrap.superadmin")


def bootstrap_superadmin() -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(User).filter(User.role == UserRole.super_admin).first()
        )
        if existing is not None:
            logger.info("Ya existe un super_admin (%s); nada que hacer.", existing.email)
            return

        email = (os.getenv("SUPERADMIN_EMAIL") or "").strip().lower()
        password = os.getenv("SUPERADMIN_PASSWORD") or ""
        name = (os.getenv("SUPERADMIN_NAME") or "Super Admin").strip()

        if not email or not password:
            logger.warning(
                "No hay super_admin y faltan SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD; "
                "se omite el bootstrap (configurá las env vars para crearlo)."
            )
            return

        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            # Email ya registrado con otro rol → elevar (sin tocar la contraseña).
            user.role = UserRole.super_admin
            user.is_active = True
            user.failed_login_attempts = 0
            user.locked_until = None
            action = "elevado a super_admin"
        else:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name=name,
                role=UserRole.super_admin,
                tier=AccessTier.enterprise,
                is_active=True,
            )
            db.add(user)
            action = "creado"
        db.commit()
        logger.info("super_admin %s: %s", action, email)
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap_superadmin()
