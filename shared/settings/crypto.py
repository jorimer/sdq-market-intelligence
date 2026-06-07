"""Symmetric encryption for stored secrets (data-source API keys, proxy secrets).

Keys live in the database, so they must be encrypted at rest. We derive a stable
Fernet key from ``SETTINGS_SECRET`` (or ``JWT_SECRET_KEY`` as a dev fallback) so
the same deployment can always decrypt what it wrote, across restarts.

The secret is never logged or returned to clients — the API only ever exposes a
boolean "is set" flag and a masked placeholder.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from shared.config.settings import settings

logger = logging.getLogger("sdq.settings.crypto")


def _fernet() -> Fernet:
    secret = settings.SETTINGS_SECRET or settings.JWT_SECRET_KEY
    # Fernet needs a 32-byte url-safe base64 key; derive one deterministically.
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a non-empty secret; empty/None passes through as ''."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret; returns '' on empty or undecryptable input.

    Undecryptable values (e.g. written under a different secret, or accidental
    plaintext) are treated as "not set" rather than raising — the operator can
    re-enter the key from the UI.
    """
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("No se pudo descifrar un secreto almacenado; se trata como vacío.")
        return ""
