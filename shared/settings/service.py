"""Business logic for in-app settings + sector data-source API configuration.

Read paths return masked output (never plaintext secrets). Write paths preserve
existing secrets when the client sends the masked placeholder. Resolution helpers
(``get_sector_api_*``) decrypt on demand for the connectors/scheduler and fall
back to env-based defaults so a fresh deployment still works.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from shared.config.settings import settings as app_settings
from shared.settings.crypto import decrypt, encrypt
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.schemas import (
    MASK,
    SectorApiIn,
    SectorApiOut,
    SettingsIn,
    SettingsOut,
    TestConnectionIn,
    TestConnectionOut,
)

logger = logging.getLogger("sdq.settings.service")

# Defaults for providers we ship knowledge of, so the UI can prefill base URLs.
KNOWN_PROVIDERS = {
    "sb_do": {
        "providerName": "Superintendencia de Bancos (SB)",
        "apiName": "API de Estadísticas del Sistema Financiero",
        "country": "DO",
        "sector": "banking",
        "baseUrl": app_settings.SIB_API_BASE_URL,
    },
}

_CLAUDE_KEY = "claude_api_key"
_LANG_KEY = "default_language"


# ── App-level key/value ───────────────────────────────────────────
def _get_app_setting(db: Session, key: str) -> Optional[AppSetting]:
    return db.query(AppSetting).filter(AppSetting.key == key).first()


def _set_app_setting(db: Session, key: str, value: str, is_secret: bool) -> None:
    row = _get_app_setting(db, key)
    stored = encrypt(value) if is_secret else value
    if row:
        row.value = stored
        row.is_secret = is_secret
    else:
        db.add(AppSetting(key=key, value=stored, is_secret=is_secret))


def get_claude_api_key(db: Session) -> str:
    """Resolve the Claude key: stored (encrypted) value, else env."""
    row = _get_app_setting(db, _CLAUDE_KEY)
    if row and row.value:
        return decrypt(row.value)
    return app_settings.ANTHROPIC_API_KEY


# ── Serialization (masked) ────────────────────────────────────────
def _to_out(cfg: SectorApiConfig) -> SectorApiOut:
    api_key = decrypt(cfg.api_key_enc or "")
    return SectorApiOut(
        id=cfg.id,
        provider=cfg.provider,
        providerName=cfg.provider_name,
        apiName=cfg.api_name,
        country=cfg.country,
        sector=cfg.sector,
        baseUrl=cfg.base_url,
        proxyUrl=cfg.proxy_url,
        enabled=cfg.enabled,
        apiKeySet=bool(api_key),
        apiKeySecondarySet=bool(decrypt(cfg.api_key_secondary_enc or "")),
        proxySecretSet=bool(decrypt(cfg.proxy_secret_enc or "")),
        apiKeyMasked=MASK if api_key else "",
        lastTestStatus=cfg.last_test_status,
        lastTestDate=cfg.last_test_date,
        lastTestDetail=cfg.last_test_detail,
    )


def get_settings(db: Session) -> SettingsOut:
    claude = _get_app_setting(db, _CLAUDE_KEY)
    lang = _get_app_setting(db, _LANG_KEY)
    apis = db.query(SectorApiConfig).order_by(SectorApiConfig.provider).all()
    return SettingsOut(
        claudeApiKeySet=bool((claude and claude.value) or app_settings.ANTHROPIC_API_KEY),
        defaultLanguage=(lang.value if lang and lang.value else app_settings.DEFAULT_LANGUAGE),
        sectorApis=[_to_out(c) for c in apis],
    )


# ── Write ─────────────────────────────────────────────────────────
def _apply_secret(current_enc: Optional[str], incoming: Optional[str]) -> Optional[str]:
    """Decide the stored ciphertext for a secret field on update.

    - ``None`` or masked placeholder → keep current (unchanged).
    - empty string → clear.
    - any other value → encrypt and store.
    """
    if incoming is None or incoming == MASK:
        return current_enc
    if incoming == "":
        return ""
    return encrypt(incoming)


def _upsert_sector_api(db: Session, payload: SectorApiIn) -> SectorApiConfig:
    cfg = (
        db.query(SectorApiConfig)
        .filter(SectorApiConfig.provider == payload.provider)
        .first()
    )
    if not cfg:
        cfg = SectorApiConfig(provider=payload.provider)
        db.add(cfg)
    cfg.provider_name = payload.providerName
    cfg.api_name = payload.apiName
    cfg.country = payload.country
    cfg.sector = payload.sector
    cfg.base_url = payload.baseUrl
    cfg.proxy_url = payload.proxyUrl
    cfg.enabled = payload.enabled
    cfg.api_key_enc = _apply_secret(cfg.api_key_enc, payload.apiKey)
    cfg.api_key_secondary_enc = _apply_secret(cfg.api_key_secondary_enc, payload.apiKeySecondary)
    cfg.proxy_secret_enc = _apply_secret(cfg.proxy_secret_enc, payload.proxySecret)
    return cfg


def update_settings(db: Session, payload: SettingsIn) -> SettingsOut:
    if payload.claudeApiKey is not None and payload.claudeApiKey != MASK:
        _set_app_setting(db, _CLAUDE_KEY, payload.claudeApiKey, is_secret=True)
    if payload.defaultLanguage is not None:
        _set_app_setting(db, _LANG_KEY, payload.defaultLanguage, is_secret=False)
    if payload.sectorApis is not None:
        for api in payload.sectorApis:
            _upsert_sector_api(db, api)
    db.commit()
    return get_settings(db)


def delete_sector_api(db: Session, provider: str) -> bool:
    cfg = db.query(SectorApiConfig).filter(SectorApiConfig.provider == provider).first()
    if not cfg:
        return False
    db.delete(cfg)
    db.commit()
    return True


# ── Resolution helpers (for connectors/scheduler) ─────────────────
def _provider(db: Session, provider: str) -> Optional[SectorApiConfig]:
    return db.query(SectorApiConfig).filter(SectorApiConfig.provider == provider).first()


def get_sector_api_key(db: Session, provider: str) -> str:
    cfg = _provider(db, provider)
    if cfg and cfg.enabled:
        key = decrypt(cfg.api_key_enc or "")
        if key:
            return key
    if provider == "sb_do":
        return app_settings.SIB_API_KEY
    return ""


def get_sector_api_key_secondary(db: Session, provider: str) -> str:
    cfg = _provider(db, provider)
    if cfg and cfg.enabled:
        return decrypt(cfg.api_key_secondary_enc or "")
    return ""


def get_sector_api_base_url(db: Session, provider: str) -> str:
    cfg = _provider(db, provider)
    if cfg and cfg.base_url:
        return cfg.base_url
    return KNOWN_PROVIDERS.get(provider, {}).get("baseUrl", "")


def get_sector_api_proxy(db: Session, provider: str) -> Tuple[str, str]:
    """Return ``(proxy_url, proxy_secret)`` for a provider, or ``("", "")``."""
    cfg = _provider(db, provider)
    if cfg and cfg.enabled and cfg.proxy_url:
        return cfg.proxy_url, decrypt(cfg.proxy_secret_enc or "")
    return "", ""


# ── Connection test ───────────────────────────────────────────────
def _normalize_base_url(base: str) -> str:
    base = (base or "").rstrip("/")
    if base and "sb.gob.do" in base and "/estadisticas" not in base:
        base = f"{base}/estadisticas/v2"
    return base


def test_connection(db: Session, payload: TestConnectionIn) -> TestConnectionOut:
    """Test connectivity to a provider's API (currently SIB), through the proxy
    if configured. Uses overrides from the payload, else the stored config.
    Persists the result on the stored config row.
    """
    import httpx

    cfg = _provider(db, payload.provider)
    base = _normalize_base_url(
        payload.baseUrl or (cfg.base_url if cfg else "")
        or KNOWN_PROVIDERS.get(payload.provider, {}).get("baseUrl", "")
    )
    api_key = payload.apiKey if payload.apiKey not in (None, MASK) else (
        decrypt(cfg.api_key_enc) if cfg and cfg.api_key_enc else ""
    )
    secondary = payload.apiKeySecondary if payload.apiKeySecondary not in (None, MASK) else (
        decrypt(cfg.api_key_secondary_enc) if cfg and cfg.api_key_secondary_enc else ""
    )
    proxy_url = (payload.proxyUrl if payload.proxyUrl is not None else (cfg.proxy_url if cfg else "")) or ""
    proxy_secret = payload.proxySecret if payload.proxySecret not in (None, MASK) else (
        decrypt(cfg.proxy_secret_enc) if cfg and cfg.proxy_secret_enc else ""
    )

    if not base:
        return _persist_test(db, cfg, "error", "Falta la URL base.", None)
    if not api_key:
        return _persist_test(db, cfg, "error", "Falta la clave de API.", None)

    # SIB lives behind Azure APIM (subscription-key header) + a Sucuri WAF that
    # blocks datacenter IPs, so a Mozilla UA is required and prod must use a proxy.
    target = f"{base}/indicadores/principales?periodoInicial=2024-01&periodoFinal=2024-03&registros=2"
    headers = {
        "Ocp-Apim-Subscription-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; SDQ-MIP/1.0)",
    }
    use_proxy = bool(proxy_url and proxy_secret)

    def _do(req_headers):
        if use_proxy:
            return httpx.post(
                f"{proxy_url.rstrip('/')}/proxy",
                json={"url": target, "headers": req_headers, "method": "GET"},
                headers={"X-Proxy-Secret": proxy_secret, "Content-Type": "application/json"},
                timeout=30,
            )
        return httpx.get(target, headers=req_headers, timeout=20)

    try:
        resp = _do(headers)
        if resp.status_code == 401 and secondary:
            resp = _do({**headers, "Ocp-Apim-Subscription-Key": secondary})
        if resp.status_code == 200:
            return _persist_test(db, cfg, "success", "Conexión exitosa", 200, use_proxy)
        if resp.status_code == 403:
            return _persist_test(
                db, cfg, "error",
                "403 — bloqueado por el WAF del SIB. Configure el proxy Cloudflare.",
                403, use_proxy,
            )
        if resp.status_code == 401:
            return _persist_test(db, cfg, "error", "401 — clave de API inválida.", 401, use_proxy)
        return _persist_test(db, cfg, "error", f"HTTP {resp.status_code}", resp.status_code, use_proxy)
    except httpx.TimeoutException:
        return _persist_test(db, cfg, "error", "Tiempo de espera agotado.", None, use_proxy)
    except httpx.ConnectError:
        return _persist_test(db, cfg, "error", "No se pudo conectar.", None, use_proxy)
    except Exception as e:  # noqa: BLE001 — surface any client error as a test failure
        return _persist_test(db, cfg, "error", str(e)[:200], None, use_proxy)


def _persist_test(
    db: Session,
    cfg: Optional[SectorApiConfig],
    status: str,
    detail: str,
    http_status: Optional[int],
    via_proxy: bool = False,
) -> TestConnectionOut:
    if cfg:
        cfg.last_test_status = status
        cfg.last_test_detail = detail
        cfg.last_test_date = datetime.now(timezone.utc).isoformat()
        db.commit()
    return TestConnectionOut(status=status, detail=detail, httpStatus=http_status, viaProxy=via_proxy)
