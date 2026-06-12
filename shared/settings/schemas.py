"""API schemas for in-app settings. Secrets are write-only.

On output we never send a stored key back — only a boolean ``*Set`` flag and a
masked placeholder. On input, the masked placeholder means "leave unchanged".
"""
from typing import List, Optional

from pydantic import BaseModel

MASK = "••••••••"


class SectorApiOut(BaseModel):
    id: str
    provider: str
    providerName: str = ""
    apiName: str = ""
    country: str = ""
    sector: str = ""
    baseUrl: str = ""
    proxyUrl: str = ""
    enabled: bool = True
    needsSecondary: bool = False  # only Azure-APIM SIB; others use a single token
    # Write-only secrets surface only as "is set" flags + a masked placeholder.
    apiKeySet: bool = False
    apiKeySecondarySet: bool = False
    proxySecretSet: bool = False
    apiKeyMasked: str = ""
    lastTestStatus: str = ""
    lastTestDate: str = ""
    lastTestDetail: str = ""


class SectorApiIn(BaseModel):
    provider: str
    providerName: str = ""
    apiName: str = ""
    country: str = ""
    sector: str = ""
    baseUrl: str = ""
    proxyUrl: str = ""
    enabled: bool = True
    # Omitted or equal to MASK → keep the stored value. Empty string → clear it.
    apiKey: Optional[str] = None
    apiKeySecondary: Optional[str] = None
    proxySecret: Optional[str] = None


class SettingsOut(BaseModel):
    claudeApiKeySet: bool = False
    defaultLanguage: str = "es"
    # Global Cloudflare WAF proxy (shared by all sources behind the WAF).
    cloudflareProxyUrl: str = ""
    cloudflareProxySecretSet: bool = False
    sectorApis: List[SectorApiOut] = []


class SettingsIn(BaseModel):
    claudeApiKey: Optional[str] = None
    defaultLanguage: Optional[str] = None
    cloudflareProxyUrl: Optional[str] = None
    cloudflareProxySecret: Optional[str] = None
    sectorApis: Optional[List[SectorApiIn]] = None


class TestConnectionIn(BaseModel):
    provider: str
    # Optional overrides; when omitted the stored config is used.
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    apiKeySecondary: Optional[str] = None
    proxyUrl: Optional[str] = None
    proxySecret: Optional[str] = None


class TestConnectionOut(BaseModel):
    status: str  # success | error
    detail: str = ""
    httpStatus: Optional[int] = None
    viaProxy: bool = False
