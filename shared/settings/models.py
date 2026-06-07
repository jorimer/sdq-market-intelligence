"""Persistence for in-app configuration: app-level settings + sector data-source APIs.

Secret columns (``*_enc``) hold Fernet ciphertext (see :mod:`shared.settings.crypto`);
they are never returned to clients in plaintext.
"""
from sqlalchemy import Boolean, Column, String, Text

from shared.database.base import Base, UUIDMixin


class AppSetting(Base):
    """Generic key/value app setting (e.g. the Claude API key, default language).

    Secret values are stored encrypted with ``is_secret=True``.
    """

    __tablename__ = "app_setting"

    key = Column(String(100), primary_key=True)
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
