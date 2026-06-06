"""Seed the Claude E2E superuser (for post-deployment end-to-end checks).

Idempotent: creates the account if missing, or restores it (admin role, active,
password reset) if it already exists.  Run after every deployment so the E2E
account is always usable.

    python scripts/seed_e2e_user.py

⚠️  This is a known-credential account for testing ONLY.  Disable it before
going live:  python scripts/seed_e2e_user.py --deactivate
"""
import argparse
import logging
import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.auth.jwt_handler import hash_password  # noqa: E402
from shared.auth.models import User, UserRole  # noqa: E402
from shared.config.settings import settings  # noqa: E402
from shared.database.session import SessionLocal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sdq.seed.e2e_user")

E2E_EMAIL = "claude@sdqconsulting.com.do"
E2E_PASSWORD = "Claude1234"
E2E_FULL_NAME = "Claude E2E (testing)"


def seed_e2e_user(deactivate: bool = False) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == E2E_EMAIL).first()

        if deactivate:
            if user is None:
                logger.info("Usuario E2E no existe; nada que desactivar.")
                return
            user.is_active = False
            db.commit()
            logger.info("Usuario E2E DESACTIVADO: %s", E2E_EMAIL)
            return

        if user is None:
            user = User(
                email=E2E_EMAIL,
                password_hash=hash_password(E2E_PASSWORD),
                full_name=E2E_FULL_NAME,
                role=UserRole.admin,
                is_active=True,
            )
            db.add(user)
            action = "creado"
        else:
            # Restore to a known-good state after a deployment.
            user.password_hash = hash_password(E2E_PASSWORD)
            user.role = UserRole.admin
            user.is_active = True
            user.failed_login_attempts = 0
            user.locked_until = None
            action = "restaurado"

        db.commit()
        logger.info(
            "Superusuario E2E %s: %s (rol=admin, activo) | DB=%s",
            action, E2E_EMAIL, settings.DATABASE_URL,
        )
        logger.warning(
            "Cuenta de credencial conocida SOLO para pruebas. "
            "Desactivar antes de salir en vivo: "
            "python scripts/seed_e2e_user.py --deactivate"
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed/restore the Claude E2E superuser")
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Desactivar el usuario E2E (antes de salir en vivo)",
    )
    args = parser.parse_args()
    seed_e2e_user(deactivate=args.deactivate)
