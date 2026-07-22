"""Acuñación y verificación de llaves de API.

**Por qué SHA-256 y no bcrypt** (que es lo que usa `shared/auth` para contraseñas): una
contraseña es de baja entropía y elegida por un humano, así que necesita un hash lento
que encarezca la fuerza bruta. Una llave de API es un secreto aleatorio de 256 bits — la
fuerza bruta es inviable por entropía, no por costo del hash. Usar bcrypt aquí agregaría
~100 ms a CADA request (se verifica en todas, no solo al login) sin ganar seguridad real.
SHA-256 sobre alta entropía es la práctica estándar para tokens portadores.

Formato: ``sdq_live_<prefix>_<secret>``. El ``prefix`` (8 chars) es público, identifica
la llave en la UI y en la bitácora, y permite buscarla en la DB sin comparar todos los
hashes. El ``secret`` (43 chars, 256 bits en base64url) es lo único que se verifica.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Optional

KEY_ENV_LIVE = "live"
KEY_ENV_TEST = "test"

_PREFIX_BYTES = 6      # → 8 chars base64url
_SECRET_BYTES = 32     # → 43 chars base64url (256 bits)
_KEY_RE = re.compile(r"^sdq_(live|test)_([A-Za-z0-9_-]{8})_([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class MintedKey:
    """Llave recién acuñada. ``token`` es lo ÚNICO que el dueño verá; no se persiste."""

    token: str
    prefix: str
    secret_hash: str


def mint_key(env: str = KEY_ENV_LIVE) -> MintedKey:
    """Genera una llave nueva. Devuelve el token completo + lo que se guarda."""
    if env not in (KEY_ENV_LIVE, KEY_ENV_TEST):
        raise ValueError(f"Entorno de llave inválido: '{env}'. Use 'live' o 'test'.")
    prefix = secrets.token_urlsafe(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return MintedKey(
        token=f"sdq_{env}_{prefix}_{secret}",
        prefix=prefix,
        secret_hash=hash_secret(secret),
    )


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_token(token: str) -> Optional[tuple]:
    """``(env, prefix, secret)`` si el token está bien formado; ``None`` si no.

    Se valida la FORMA antes de tocar la DB: un token mal formado no debe costar una
    consulta, y así un atacante no puede usar el tiempo de respuesta para inferir si un
    prefijo existe."""
    if not token:
        return None
    m = _KEY_RE.match(token.strip())
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3))


def verify_secret(secret: str, secret_hash: str) -> bool:
    """Comparación en tiempo constante (``compare_digest``) — evita que el tiempo de
    respuesta filtre cuántos caracteres del hash coincidieron."""
    return hmac.compare_digest(hash_secret(secret), secret_hash or "")
