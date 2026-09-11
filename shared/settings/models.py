"""Persistence for in-app configuration: app-level settings + sector data-source APIs.

Secret columns (``*_enc``) hold Fernet ciphertext (see :mod:`shared.settings.crypto`);
they are never returned to clients in plaintext.
"""
import hashlib

from sqlalchemy import Boolean, Column, String, Text

from shared.database.base import Base, UUIDMixin

#: Largo de ``app_setting.key``. PostgreSQL lo aplica y SQLite no: una clave más larga pasa
#: todos los tests y revienta en producción (ver :func:`clave_acotada`).
LARGO_CLAVE = 100

_HUELLA = "sha256"
_LARGO_HUELLA = 48


def clave_acotada(prefijo: str, resto: str) -> str:
    """``{prefijo}:{resto}`` si entra en ``app_setting.key``; si no, ``{prefijo}:sha256:<huella>``.

    Para toda clave que se arma con partes variables (UUIDs, nombres de regla, claves de
    informe). El 2026-09-10 un marcador de dedup de 119 caracteres fue rechazado en cada
    barrido de alertas, y como la notificación ya estaba comprometida el cliente recibía la
    misma alerta una y otra vez.

    **La huella se aplica solo a lo que no entra**, a propósito: todo marcador que ya existe
    en producción mide ≤ :data:`LARGO_CLAVE` (PostgreSQL rechazó los demás), así que conserva
    su clave y no hace falta migrar nada. Hashear todas habría borrado de hecho los marcadores
    sin vencimiento de ``readiness_cross`` y re-enviado cada «Listo para publicar». La clave
    sigue siendo determinista: la misma entrada da siempre la misma clave, que es lo único que
    necesitan leer, marcar y limpiar.

    Levanta ``ValueError`` si el prefijo no deja lugar a la huella: mejor al importar el
    consumidor que en el primer aviso largo.
    """
    forma_con_huella = len(prefijo) + len(f"::{_HUELLA}") + _LARGO_HUELLA
    if forma_con_huella > LARGO_CLAVE:
        raise ValueError(
            f"el prefijo {prefijo!r} no deja lugar a la huella en app_setting.key "
            f"({forma_con_huella} > {LARGO_CLAVE})")
    literal = f"{prefijo}:{resto}"
    if len(literal) <= LARGO_CLAVE:
        return literal
    huella = hashlib.sha256(resto.encode("utf-8")).hexdigest()[:_LARGO_HUELLA]
    return f"{prefijo}:{_HUELLA}:{huella}"


class AppSetting(Base):
    """Generic key/value app setting (e.g. the Claude API key, default language).

    Secret values are stored encrypted with ``is_secret=True``. A key built from variable
    parts must go through :func:`clave_acotada` (enforced by
    ``shared/tests/test_lo_que_sqlite_no_vigila.py``).
    """

    __tablename__ = "app_setting"

    key = Column(String(LARGO_CLAVE), primary_key=True)
    value = Column(Text, nullable=True)  # plaintext, or ciphertext when is_secret
    is_secret = Column(Boolean, default=False, nullable=False)


class SectorApiConfig(UUIDMixin, Base):
    """A configurable benchmark/data-source API for one sector + country.

    Mirrors the original app's ``sectorApis`` entries so the ported SIB ETL and
    its scheduler can resolve credentials from here. ``provider`` is the stable
    key the connectors look up (e.g. ``"sb_do"``).
    """

    __tablename__ = "sector_api_config"

    provider = Column(String(50), unique=True, nullable=False, index=True)
    provider_name = Column(String(150), nullable=False, default="")
    api_name = Column(String(150), nullable=False, default="")
    country = Column(String(10), nullable=False, default="")
    sector = Column(String(50), nullable=False, default="")
    base_url = Column(String(500), nullable=False, default="")

    # Secrets (Fernet ciphertext)
    api_key_enc = Column(Text, nullable=True)
    api_key_secondary_enc = Column(Text, nullable=True)
    proxy_secret_enc = Column(Text, nullable=True)

    proxy_url = Column(String(500), nullable=False, default="")
    enabled = Column(Boolean, default=True, nullable=False)

    last_test_status = Column(String(20), nullable=False, default="")  # success|error|""
    last_test_date = Column(String(40), nullable=False, default="")     # ISO timestamp
    last_test_detail = Column(Text, nullable=False, default="")
