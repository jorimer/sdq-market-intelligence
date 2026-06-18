"""Production bootstrap — create the first admin (and optional data) in an empty DB.

After a deploy to a fresh database the schema exists (migrations run on startup)
but there are no users, so nobody can log in.  This script creates the initial
admin from environment variables.  Idempotent: existing users are left untouched.

Run once from the platform's shell / one-off (e.g. Railway):

    ADMIN_EMAIL=you@org.com ADMIN_PASSWORD='strong-pass' \
        python scripts/prod_seed.py [--with-e2e] [--with-banking]

Flags:
    --with-e2e      also create the Claude E2E user (scripts/seed_e2e_user).
    --with-banking  also seed the banking entity *catalog* (35 entities, no data).

Security: role elevation is server-side only — the public /auth/register always
creates a 'viewer'. This script is the controlled path to the first admin.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.auth.jwt_handler import hash_password  # noqa: E402
from shared.auth.models import User, UserRole  # noqa: E402
from shared.config.settings import settings  # noqa: E402
from shared.database.session import SessionLocal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sdq.prod_seed")


def create_admin(db) -> bool:
    """Create the admin from ADMIN_EMAIL/ADMIN_PASSWORD if missing. Returns created?"""
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    name = os.environ.get("ADMIN_NAME", "Administrador")
    if not email or not password:
        logger.warning("ADMIN_EMAIL/ADMIN_PASSWORD no definidos; omito creación de admin.")
        return False

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        logger.info("El admin ya existe: %s (sin cambios).", email)
        return False

    db.add(User(
        email=email,
        password_hash=hash_password(password),
        full_name=name,
        role=UserRole.admin,
        is_active=True,
    ))
    db.commit()
    logger.info("Admin creado: %s (rol=admin)", email)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap de producción (admin inicial)")
    parser.add_argument("--with-e2e", action="store_true", help="Crear también el usuario E2E Claude")
    parser.add_argument("--with-banking", action="store_true", help="Sembrar el catálogo de entidades de banca (sin datos)")
    args = parser.parse_args()

    logger.info("DB destino: %s", settings.DATABASE_URL.split("@")[-1])
    db = SessionLocal()
    try:
        create_admin(db)
    finally:
        db.close()

    if args.with_e2e:
        from scripts.seed_e2e_user import seed_e2e_user
        seed_e2e_user()

    if args.with_banking:
        from modules.banking_score.seed.banking_seed import seed_banks
        result = seed_banks(verbose=False)
        logger.info("Seed banca: %s", {k: result.get(k) for k in list(result)[:4]})


if __name__ == "__main__":
    main()
