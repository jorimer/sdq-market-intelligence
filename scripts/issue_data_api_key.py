"""Emitir una llave de la Data API para un consumidor (operación one-off, idempotente).

Uso (dentro del contenedor del servicio web, que alcanza la DB interna):

    railway ssh "python scripts/issue_data_api_key.py"                    # defaults = SDQ-PMS
    DATA_API_KEY_EMAIL=otro@cliente.com railway ssh "python scripts/issue_data_api_key.py"

Crea (si no existe) el usuario de servicio dueño de la llave — tier enterprise, rol
viewer, contraseña aleatoria que NO se revela: nadie inicia sesión web con esta cuenta;
su único propósito es que la llave herede sus entitlements — y emite la llave. El token
se imprime UNA sola vez; si se pierde, se revoca y se emite otra (solo se guarda el hash).

Idempotente: si ya hay una llave activa con el mismo nombre, no emite otra (rotar =
revocar primero desde /api/v1/admin/data-api/keys/{id}/revoke).
"""
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth.jwt_handler import hash_password  # noqa: E402
from shared.auth.models import AccessTier, User, UserRole  # noqa: E402
from shared.data_api.service import create_key, list_keys  # noqa: E402
from shared.database.session import SessionLocal  # noqa: E402

EMAIL = os.environ.get("DATA_API_KEY_EMAIL", "pms@sdqconsulting.com.do")
FULL_NAME = os.environ.get("DATA_API_KEY_NAME", "SDQ-PMS (servicio)")
KEY_NAME = os.environ.get("DATA_API_KEY_LABEL", "SDQ-PMS · producción")
CLIENT_REF = os.environ.get("DATA_API_KEY_REF", "sdq-pms")
# "internal" = insumo de análisis propio (el dato no sale hacia terceros) — el caso PMS.
USAGE = os.environ.get("DATA_API_KEY_USAGE", "internal")
RATE = int(os.environ.get("DATA_API_KEY_RATE", "120"))
# Sin tope mensual por default (uso interno del grupo). Cliente externo: SIEMPRE con tope.
QUOTA = os.environ.get("DATA_API_KEY_QUOTA") or None


def main() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == EMAIL).one_or_none()
        if user is None:
            user = User(
                email=EMAIL,
                password_hash=hash_password(secrets.token_urlsafe(32)),  # no se revela
                full_name=FULL_NAME,
                role=UserRole.viewer,
                tier=AccessTier.enterprise,
                is_active=True,
            )
            db.add(user)
            db.commit()
            print(f"Usuario de servicio creado: {EMAIL} (tier=enterprise, rol=viewer)")
        else:
            print(f"Usuario ya existe: {EMAIL} (tier={getattr(user.tier, 'value', user.tier)}, "
                  f"activo={user.is_active})")

        active = [k for k in list_keys(db, user_id=user.id)
                  if k["active"] and k["name"] == KEY_NAME]
        if active:
            print(f"Ya hay una llave activa '{KEY_NAME}' (prefix {active[0]['prefix']}). "
                  f"No se emite otra — para rotar, revocar primero.")
            return 0

        out = create_key(
            db, user_id=user.id, name=KEY_NAME, client_ref=CLIENT_REF, usage=USAGE,
            rate_limit_per_minute=RATE,
            quota_per_month=int(QUOTA) if QUOTA else None,
            note=f"Emitida por scripts/issue_data_api_key.py (usage={USAGE}).",
        )
        print("\n=== LLAVE EMITIDA — GUARDAR AHORA; NO SE PUEDE VOLVER A MOSTRAR ===")
        print(out["token"])
        print(f"prefix: {out['prefix']} · usage: {out['usage']} · rate: {RATE}/min · "
              f"cuota mensual: {QUOTA or 'sin tope'}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
