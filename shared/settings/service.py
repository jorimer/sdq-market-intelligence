"""Business logic for in-app settings + sector data-source API configuration.

Read paths return masked output (never plaintext secrets). Write paths preserve
existing secrets when the client sends the masked placeholder. Resolution helpers
(``get_sector_api_*``) decrypt on demand for the connectors/scheduler and fall
back to env-based defaults so a fresh deployment still works.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

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

# Catalog of data sources discovered for each sector (2026-06). Pre-seeded into
# the config so the operator only fills the bits that depend on them: API keys
# and (for the SIB) the Cloudflare proxy. ``requires_key`` is informational for
# the UI; ``needs_proxy`` flags sources behind a WAF (only the SIB today).
KNOWN_PROVIDERS = [
    {
        "provider": "sb_do",
        "providerName": "Superintendencia de Bancos (SB)",
        "apiName": "API de Estadísticas del Sistema Financiero",
        "country": "DO",
        "sector": "banking",
        "baseUrl": app_settings.SIB_API_BASE_URL,
        "requires_key": True,
        "needs_proxy": True,
        "notes": "Clave en desarrollador.sb.gob.do (Azure APIM). Requiere proxy Cloudflare (WAF).",
    },
    {
        "provider": "bcrd",
        "providerName": "Banco Central (BCRD)",
        "apiName": "API de Estadísticas Macroeconómicas",
        "country": "DO",
        "sector": "macro",
        "baseUrl": "https://api.bancentral.gov.do",
        "requires_key": True,
        "needs_proxy": False,
        "notes": "Token tras registro en apibcrd.bancentral.gov.do.",
    },
    {
        "provider": "one_do",
        "providerName": "Datos Abiertos (ONE / datos.gob.do)",
        "apiName": "API CKAN de Datos Abiertos",
        "country": "DO",
        "sector": "social",
        "baseUrl": "https://datos.gob.do/api/3",
        "requires_key": False,
        "needs_proxy": False,
        "notes": "Pública (ODbL). Sin clave.",
    },
    {
        "provider": "comtrade",
        "providerName": "UN Comtrade",
        "apiName": "API pública de comercio exterior",
        "country": "DO",
        "sector": "trade",
        "baseUrl": "https://comtradeapi.un.org/public/v1",
        "requires_key": False,
        "needs_proxy": False,
        "notes": "Pública (reporter 214). Clave opcional para volumen.",
    },
    {
        "provider": "wgi",
        "providerName": "Banco Mundial — WGI",
        "apiName": "World Bank Indicators API",
        "country": "DO",
        "sector": "governance",
        "baseUrl": "https://api.worldbank.org/v2",
        "requires_key": False,
        "needs_proxy": False,
        "notes": "Pública (CC BY). Sin clave.",
    },
]


def _known_base_url(provider: str) -> str:
    for src in KNOWN_PROVIDERS:
        if src["provider"] == provider:
            return src.get("baseUrl", "")
    return ""


def ensure_known_sources(db: Session) -> int:
    """Seed the discovered data sources (keyless, disabled) so they show up in
    Configuración ready for the operator to add credentials. Idempotent: a source
    is inserted only if no config exists for its provider id AND none exists for
    its sector (so an operator's own banking entry isn't duplicated).
    """
    existing = db.query(SectorApiConfig).all()
    providers = {c.provider for c in existing}
    sectors = {(c.sector or "").strip().lower() for c in existing}
    added = 0
    for src in KNOWN_PROVIDERS:
        if src["provider"] in providers or src["sector"].lower() in sectors:
            continue
        db.add(SectorApiConfig(
            provider=src["provider"],
            provider_name=src["providerName"],
            api_name=src["apiName"],
            country=src["country"],
            sector=src["sector"],
            base_url=src["baseUrl"],
            enabled=False,  # operator enables after entering the key
        ))
        added += 1
    if added:
        db.commit()
    return added

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
    ensure_known_sources(db)  # pre-populate discovered sources (idempotent)
    claude = _get_app_setting(db, _CLAUDE_KEY)
    lang = _get_app_setting(db, _LANG_KEY)
    apis = db.query(SectorApiConfig).order_by(SectorApiConfig.sector, SectorApiConfig.provider).all()
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
    return _known_base_url(provider)


def get_sector_api_proxy(db: Session, provider: str) -> Tuple[str, str]:
    """Return ``(proxy_url, proxy_secret)`` for a provider, or ``("", "")``."""
    cfg = _provider(db, provider)
    if cfg and cfg.enabled and cfg.proxy_url:
        return cfg.proxy_url, decrypt(cfg.proxy_secret_enc or "")
    return "", ""


def find_banking_source(db: Session) -> Optional[SectorApiConfig]:
    """Resolve the SIB banking data source WITHOUT depending on a magic provider
    id. Preference order among *enabled* configs:
      1. provider == "sb_do" (the canonical id), else
      2. any provider with sector == "banking", preferring country "DO".

    This lets an operator name the provider anything (e.g. "SDQFinAnalyst") and
    still have the banking connector find it, as long as sector=banking.
    """
    rows = db.query(SectorApiConfig).filter(SectorApiConfig.enabled).all()
    for r in rows:
        if r.provider == "sb_do":
            return r
    banking = [r for r in rows if (r.sector or "").strip().lower() == "banking"]
    do_first = [r for r in banking if (r.country or "").strip().upper() == "DO"]
    return (do_first or banking or [None])[0]


def get_sib_credentials(db: Session) -> Dict[str, str]:
    """Resolve SIB credentials for the banking connector (sector-based, see
    :func:`find_banking_source`), with env/config fallbacks."""
    cfg = find_banking_source(db)
    if cfg:
        proxy_url = cfg.proxy_url or ""
        return {
            "api_key": decrypt(cfg.api_key_enc or "") or app_settings.SIB_API_KEY,
            "api_key_secondary": decrypt(cfg.api_key_secondary_enc or ""),
            "base_url": cfg.base_url or app_settings.SIB_API_BASE_URL,
            "proxy_url": proxy_url,
            "proxy_secret": decrypt(cfg.proxy_secret_enc or "") if proxy_url else "",
        }
    return {
        "api_key": app_settings.SIB_API_KEY,
        "api_key_secondary": "",
        "base_url": app_settings.SIB_API_BASE_URL,
        "proxy_url": "",
        "proxy_secret": "",
    }


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
        or _known_base_url(payload.provider)
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
        # The Cloudflare Worker tags every *relayed* upstream response with an
        # `X-Proxy-Status` header. Its absence on an error means the Worker itself
        # rejected us (bad proxy secret) — it never reached the SIB. This lets us
        # say WHICH key failed: the proxy secret or the SIB API key.
        relayed = use_proxy and _has_proxy_relay(resp)
        # Only retry with the secondary SIB key when the SIB actually answered.
        if resp.status_code == 401 and secondary and (not use_proxy or relayed):
            resp = _do({**headers, "Ocp-Apim-Subscription-Key": secondary})
            relayed = use_proxy and _has_proxy_relay(resp)
        if resp.status_code == 200:
            return _persist_test(db, cfg, "success", "Conexión exitosa", 200, use_proxy)
        if resp.status_code == 401:
            if use_proxy and not relayed:
                msg = "401 — secreto del proxy (Cloudflare) inválido. Revise 'Secreto del proxy'."
            else:
                msg = "401 — clave de API del SIB inválida. Revise 'Clave de API'."
            return _persist_test(db, cfg, "error", msg, 401, use_proxy)
        if resp.status_code == 403:
            if use_proxy and not relayed:
                msg = "403 — el proxy Cloudflare rechazó la solicitud (host o secreto no permitido)."
            elif use_proxy:
                msg = "403 — el SIB rechazó la solicitud (vía proxy)."
            else:
                msg = "403 — bloqueado por el WAF del SIB. Configure el proxy Cloudflare."
            return _persist_test(db, cfg, "error", msg, 403, use_proxy)
        # Any other status: if proxying and not relayed, the Worker erred itself.
        origin = "proxy Cloudflare" if (use_proxy and not relayed) else "SIB"
        return _persist_test(db, cfg, "error", f"HTTP {resp.status_code} ({origin})", resp.status_code, use_proxy)
    except httpx.TimeoutException:
        return _persist_test(db, cfg, "error", "Tiempo de espera agotado.", None, use_proxy)
    except httpx.ConnectError:
        return _persist_test(db, cfg, "error", "No se pudo conectar.", None, use_proxy)
    except Exception as e:  # noqa: BLE001 — surface any client error as a test failure
        return _persist_test(db, cfg, "error", str(e)[:200], None, use_proxy)


def _has_proxy_relay(resp) -> bool:
    """True if the response carries the Worker's ``X-Proxy-Status`` header,
    i.e. the proxy forwarded an upstream (SIB) response rather than rejecting
    the request itself."""
    try:
        return any(k.lower() == "x-proxy-status" for k in resp.headers.keys())
    except Exception:  # noqa: BLE001
        return False


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
