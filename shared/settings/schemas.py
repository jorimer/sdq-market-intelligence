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


class SmtpOut(BaseModel):
    """Correo saliente, en la forma que SÍ puede cruzar la API.

    ``passwordSet`` y no la contraseña: un campo que devuelve su propio secreto es una
    filtración con formulario. ``configurado`` se computa acá y no lo deduce el cliente —
    la regla es «sin host no hay canal» y vive en un solo lugar."""
    host: str = ""
    port: int = 587
    user: str = ""
    fromAddress: str = ""
    starttls: bool = True
    passwordSet: bool = False
    configurado: bool = False
    # Qué falta para que el canal exista, en palabras de la PANTALLA. No nombra variables de
    # entorno: el operador ya no las toca, y mandarlo a buscarlas sería una instrucción falsa.
    falta: List[str] = []


class SmtpIn(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    fromAddress: Optional[str] = None
    starttls: Optional[bool] = None
    # Omitida o igual a MASK → se conserva la guardada. Cadena vacía → se borra.
    # Sin esta distinción, cada guardado de la pantalla —que nunca recibe la contraseña
    # actual— borraría la llave al reenviar el formulario.
    password: Optional[str] = None


class SettingsOut(BaseModel):
    claudeApiKeySet: bool = False
    defaultLanguage: str = "es"
    # Techo DIARIO de gasto del modelo en USD (0 = sin techo). Se devuelve el VIGENTE:
    # el configurado por el admin si lo hay, si no el del entorno.
    llmDailyBudgetUsd: float = 0.0
    # ¿El contador del día es compartido entre workers (Redis) o uno por worker? Sin esto,
    # el techo mostrado puede ser exacto o multiplicarse por la cantidad de workers, y quien
    # lo mira no tiene forma de saber cuál de las dos cosas está viendo.
    llmBudgetCounterShared: bool = False
    # Global Cloudflare WAF proxy (shared by all sources behind the WAF).
    cloudflareProxyUrl: str = ""
    cloudflareProxySecretSet: bool = False
    sectorApis: List[SectorApiOut] = []
    smtp: SmtpOut = SmtpOut()


class SettingsIn(BaseModel):
    claudeApiKey: Optional[str] = None
    defaultLanguage: Optional[str] = None
    # 0 apaga el corte a propósito; negativo se rechaza. Omitido = sin cambios.
    llmDailyBudgetUsd: Optional[float] = None
    cloudflareProxyUrl: Optional[str] = None
    cloudflareProxySecret: Optional[str] = None
    sectorApis: Optional[List[SectorApiIn]] = None
    smtp: Optional[SmtpIn] = None


class TestConnectionIn(BaseModel):
    provider: str
    # Optional overrides; when omitted the stored config is used.
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    apiKeySecondary: Optional[str] = None
    proxyUrl: Optional[str] = None
    proxySecret: Optional[str] = None


class SmtpTestOut(BaseModel):
    """Resultado de la prueba de correo. ``detail`` trae el error REAL del servidor: sin él,
    quien acaba de pegar una llave tiene que adivinar entre llave mal copiada, puerto
    bloqueado y remitente sin verificar."""
    status: str  # success | error
    detail: str = ""
    destinatario: str = ""


class TestConnectionOut(BaseModel):
    status: str  # success | error
    detail: str = ""
    httpStatus: Optional[int] = None
    viaProxy: bool = False
