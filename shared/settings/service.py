"""Business logic for in-app settings + sector data-source API configuration.

Read paths return masked output (never plaintext secrets). Write paths preserve
existing secrets when the client sends the masked placeholder. Resolution helpers
(``get_sector_api_*``) decrypt on demand for the connectors/scheduler and fall
back to env-based defaults so a fresh deployment still works.
"""
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

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
        "needs_secondary": True,  # Azure APIM: primary + secondary subscription keys
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
        # El eje de evaluación de leyes necesita saber si una norma se dictó y cuándo, para
        # convertir obligaciones declaradas a mano en hechos con fecha. JurisAI expone su
        # base normativa; la clave la coloca el dueño desde Configuración.
        #
        # `baseUrl` va VACÍA a propósito: no hay una URL conocida que adivinar, y una
        # incorrecta por defecto haría fallar la prueba de conexión culpando a la clave.
        "provider": "jurisai",
        "providerName": "JurisAI",
        "apiName": "API de verificación normativa",
        "country": "DO",
        "sector": "law",
        "baseUrl": "https://api.jurisai.do/api/v1",
        # URLs que ESTE repo sirvió como default y que el emisor retiró. Se migran solas
        # (ver `migrar_urls_obsoletas`) porque el modo de fallar es silencioso: el host
        # viejo sigue respondiendo 200 con la misma credencial y las mismas rutas. No hay
        # error, no hay aviso y no hay fecha de corte — una integración que se quede
        # apuntando ahí funciona igual hasta el día que el dominio prestado desaparezca.
        "obsoleteBaseUrls": ["https://jurisai-production.up.railway.app/api/v1"],
        "requires_key": True,
        "needs_proxy": False,
        "notes": ("Base normativa dominicana: existencia, fecha de promulgación, Gaceta y "
                  "vigencia. La clave tiene forma `jrs_<prefijo>_<secreto>` y viaja como "
                  "`Authorization: Bearer`. Desde 2026-08-19 el emisor tiene dominio propio "
                  "(`api.jurisai.do`); el anterior lo generaba Railway y no estaba bajo su "
                  "control. Sigue siendo editable y no está incrustada en el conector."),
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
        "providerName": "Banco Mundial — Data360 (WGI/WDI)",
        "apiName": "World Bank Data360 API",
        "country": "DO",
        "sector": "governance",
        "baseUrl": "https://data360api.worldbank.org",
        "requires_key": False,
        "needs_proxy": False,
        "notes": "Pública (CC BY), sin clave. Endpoint /data360/data (REF_AREA=DOM, paginado por skip).",
    },
]


def _known_base_url(provider: str) -> str:
    for src in KNOWN_PROVIDERS:
        if src["provider"] == provider:
            return src.get("baseUrl", "")
    return ""


def _provider_needs_secondary(provider: str) -> bool:
    """Whether a provider uses a secondary key (only Azure-APIM SIB). Others (e.g.
    BCRD) get a single token, so the UI hides the secondary field."""
    for src in KNOWN_PROVIDERS:
        if src["provider"] == provider:
            return bool(src.get("needs_secondary", False))
    return False


def migrar_urls_obsoletas(db: Session) -> int:
    """Reescribe las base_url guardadas que siguen apuntando a un default que RETIRAMOS.

    **Solo toca lo que este repo sirvió como default y el emisor dio de baja.** Una URL que
    el operador escribió a mano queda intacta: no sabemos por qué la puso y pisarla sería
    peor que dejarla vieja.

    Existe porque `ensure_known_sources` es idempotente por PROVEEDOR —salta si el proveedor
    ya está— y nunca actualiza una fila existente. Sin esto, cambiar la constante arregla las
    instalaciones nuevas y deja a las que ya funcionaban apuntando al host retirado.

    Y el modo de fallar es el silencioso: el host viejo de JurisAI sigue devolviendo 200 con
    la misma credencial y las mismas rutas. Nadie se entera hasta que el dominio prestado
    deja de existir, y para entonces el entregable ya está con el cliente.
    """
    obsoletas: Dict[str, Tuple[Set[str], str]] = {}
    for src in KNOWN_PROVIDERS:
        viejas = src.get("obsoleteBaseUrls")
        if not isinstance(viejas, (list, tuple, set)) or not viejas:
            continue
        obsoletas[str(src["provider"]).lower()] = ({str(u) for u in viejas},
                                                   str(src.get("baseUrl") or ""))
    if not obsoletas:
        return 0
    migradas = 0
    for cfg in db.query(SectorApiConfig).all():
        # Se compara en minúsculas: en producción convivían `jurisai`, sembrada por el
        # catálogo, y `JurisAI`, creada a mano por el operador. La segunda queda inerte
        # —la resolución es exacta— pero su URL vieja sigue a la vista y confunde a quien
        # la edite, así que también se migra.
        par = obsoletas.get(str(cfg.provider or "").lower())
        if par is None:
            continue
        viejas_urls, nueva = par
        if str(cfg.base_url or "").strip() in viejas_urls:
            logger.info("settings: %s migra de %s a %s", cfg.provider, cfg.base_url, nueva)
            cfg.base_url = nueva  # type: ignore[assignment]
            migradas += 1
    if migradas:
        db.commit()
    return migradas


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
# Cloudflare WAF proxy — GLOBAL (one credential shared by every source behind the
# WAF), like the Claude key. Replaces the per-provider proxy fields.
_PROXY_URL_KEY = "cloudflare_proxy_url"
_PROXY_SECRET_KEY = "cloudflare_proxy_secret"


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


def get_proxy_config(db: Session) -> tuple:
    """Resolve the GLOBAL Cloudflare proxy ``(url, secret)``. Falls back to the
    banking source's per-config proxy (pre-migration / backward compat)."""
    url_row = _get_app_setting(db, _PROXY_URL_KEY)
    sec_row = _get_app_setting(db, _PROXY_SECRET_KEY)
    url = (url_row.value if url_row else "") or ""
    secret = decrypt(sec_row.value) if (sec_row and sec_row.value) else ""
    if url and secret:
        return url, secret
    # Backward-compat: the live SIB proxy used to live on its SectorApiConfig.
    cfg = find_banking_source(db)
    if cfg and cfg.proxy_url:
        return cfg.proxy_url, decrypt(cfg.proxy_secret_enc or "")
    return url, secret


def _migrate_proxy_to_global(db: Session) -> None:
    """One-time: if no global proxy is set but the SIB source carries one, copy it
    to the global setting so the operator manages it in a single place."""
    if _get_app_setting(db, _PROXY_URL_KEY):
        return
    cfg = find_banking_source(db)
    if cfg and cfg.proxy_url and (decrypt(cfg.proxy_secret_enc or "")):
        _set_app_setting(db, _PROXY_URL_KEY, cfg.proxy_url, is_secret=False)
        _set_app_setting(db, _PROXY_SECRET_KEY, decrypt(cfg.proxy_secret_enc or ""), is_secret=True)
        db.commit()


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
        needsSecondary=_provider_needs_secondary(cfg.provider),
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
    migrar_urls_obsoletas(db)  # host retirado por el emisor → el vigente (idempotente)
    _migrate_proxy_to_global(db)  # one-time: SIB per-config proxy → global
    claude = _get_app_setting(db, _CLAUDE_KEY)
    lang = _get_app_setting(db, _LANG_KEY)
    proxy_url, proxy_secret = get_proxy_config(db)
    apis = db.query(SectorApiConfig).order_by(SectorApiConfig.sector, SectorApiConfig.provider).all()
    return SettingsOut(
        claudeApiKeySet=bool((claude and claude.value) or app_settings.ANTHROPIC_API_KEY),
        defaultLanguage=(lang.value if lang and lang.value else app_settings.DEFAULT_LANGUAGE),
        cloudflareProxyUrl=proxy_url,
        cloudflareProxySecretSet=bool(proxy_secret),
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
    if payload.cloudflareProxyUrl is not None:
        _set_app_setting(db, _PROXY_URL_KEY, payload.cloudflareProxyUrl, is_secret=False)
    if payload.cloudflareProxySecret is not None and payload.cloudflareProxySecret != MASK:
        _set_app_setting(db, _PROXY_SECRET_KEY, payload.cloudflareProxySecret, is_secret=True)
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


def _test_jurisai_connection(db, cfg, base: str, api_key: str) -> TestConnectionOut:
    """Prueba contra el endpoint REAL de JurisAI, con el contrato que declaró el emisor.

    Se consulta `/normas` **con rango explícito** y no la raíz: sin `desde` y `hasta` el
    emisor calcula el alcance desde 1900 y `vacio_es_concluyente` sale siempre false, así
    que una prueba sin rango pasaría aunque la respuesta no sirva para nada de lo que este
    eje necesita — y lo que el eje necesita es poder afirmar que una norma NO se dictó.

    El 401 se reporta sin adivinar cuál de las tres causas fue —clave inválida, revocada o
    sin permiso—: el emisor no las distingue a propósito, y fingir precisión mandaría a
    revisar lo que no es.
    """
    import httpx

    target = (f"{base.rstrip('/')}/normas?cita_a=ley:1-12&tipo=decreto"
              f"&desde=2012-01-25&hasta=2026-12-31&limite=1")
    try:
        resp = httpx.get(target, headers={"Authorization": f"Bearer {api_key}",
                                          "Accept": "application/json"},
                         timeout=25, follow_redirects=True)
    except httpx.HTTPError as e:
        return _persist_test(db, cfg, "error",
                             f"No se pudo alcanzar {base} ({type(e).__name__}).", None)
    if resp.status_code == 401:
        return _persist_test(db, cfg, "error",
                             "JurisAI rechazó la credencial (401). El emisor no distingue "
                             "entre clave inválida, revocada o sin permiso.", 401)
    if resp.status_code >= 400:
        return _persist_test(db, cfg, "error",
                             f"JurisAI respondió {resp.status_code} en /normas.",
                             resp.status_code)
    try:
        alcance = (resp.json().get("alcance") or {})
    except Exception:  # noqa: BLE001
        return _persist_test(db, cfg, "error",
                             "La respuesta no trae el bloque `alcance` en JSON.",
                             resp.status_code)
    concluyente = bool(alcance.get("vacio_es_concluyente"))
    # El HOST se nombra en el resultado. Parece redundante y es la única defensa contra el
    # cambio silencioso de dominio: cuando el emisor migró a `api.jurisai.do` el host viejo
    # siguió devolviendo 200 con la misma clave y las mismas rutas, así que una prueba que
    # dijera solo «Conectado» habría dado verde apuntando al host retirado. Quien lea el
    # resultado tiene que poder ver CONTRA QUÉ se conectó, sin ir a buscarlo a otra pantalla.
    host = urllib.parse.urlsplit(base).netloc or base
    # La HUELLA del corpus (`instantanea`), no `medido_al`. El emisor corrigió esta lectura
    # con evidencia: en unas horas su corpus creció 546 normas y `medido_al` no se movió ni un
    # segundo, porque no es una marca de frescura sino el piso de antigüedad de la evidencia.
    # Para una prueba de conexión, lo informativo es el tamaño vivo del corpus.
    inst = alcance.get("instantanea") or {}
    leidas = inst.get("normas_leidas") if isinstance(inst, dict) else None
    return _persist_test(
        db, cfg, "success",
        f"Conectado a {host}. Con rango explícito el alcance es "
        + ("concluyente: un resultado vacío SÍ autoriza a afirmar que la norma no se dictó."
           if concluyente else
           "NO concluyente: un resultado vacío no autorizaría a afirmar incumplimiento.")
        + (f" Corpus vivo: {leidas} normas leídas." if leidas is not None else
           " El emisor no declara la huella del corpus."),
        resp.status_code)


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
    proxy_url, proxy_secret = get_proxy_config(db)
    cfg = find_banking_source(db)
    if cfg:
        return {
            "api_key": decrypt(cfg.api_key_enc or "") or app_settings.SIB_API_KEY,
            "api_key_secondary": decrypt(cfg.api_key_secondary_enc or ""),
            "base_url": cfg.base_url or app_settings.SIB_API_BASE_URL,
            "proxy_url": proxy_url,
            "proxy_secret": proxy_secret,
        }
    return {
        "api_key": app_settings.SIB_API_KEY,
        "api_key_secondary": "",
        "base_url": app_settings.SIB_API_BASE_URL,
        "proxy_url": proxy_url,
        "proxy_secret": proxy_secret,
    }


# ── Connection test ───────────────────────────────────────────────
def _normalize_base_url(base: str) -> str:
    base = (base or "").rstrip("/")
    if base and "sb.gob.do" in base and "/estadisticas" not in base:
        base = f"{base}/estadisticas/v2"
    return base


def _test_bcrd_connection(db: Session, cfg, base: str, token: str) -> TestConnectionOut:
    """Probe the BCRD API with its real contract: POST ``{"token": …}`` to a
    MacroVariables endpoint. Direct (no proxy/WAF) against the configured host.
    """
    import httpx

    from shared.data.bcrd_api import BcrdApiError, fetch_bcrd_variable

    try:
        fetch_bcrd_variable(token, "inflacion", base_url=base, timeout=20)
        return _persist_test(db, cfg, "success", "Conexión exitosa", 200, False)
    except BcrdApiError as e:
        # The BCRD rejects a bad token as an app-level error (HTTP 500 body).
        if e.is_auth:
            msg = f"Token del BCRD rechazado: {e.message}. Revise 'Clave de API / Token'."
        else:
            msg = f"BCRD: {e.message}"
        return _persist_test(db, cfg, "error", msg, e.http_status, False)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code if e.response is not None else None
        if code == 401:
            msg = "401 — token del BCRD inválido. Revise 'Clave de API / Token'."
        elif code == 403:
            msg = "403 — el BCRD rechazó la solicitud (token o permisos)."
        else:
            msg = f"HTTP {code} (BCRD)"
        return _persist_test(db, cfg, "error", msg, code, False)
    except httpx.TimeoutException:
        return _persist_test(db, cfg, "error", "Tiempo de espera agotado.", None, False)
    except httpx.ConnectError:
        return _persist_test(db, cfg, "error", "No se pudo conectar al BCRD.", None, False)
    except Exception as e:  # noqa: BLE001 — surface any client error as a test failure
        return _persist_test(db, cfg, "error", str(e)[:200], None, False)


def test_connection(db: Session, payload: TestConnectionIn) -> TestConnectionOut:
    """Test connectivity to a provider's API (SIB or BCRD), through the proxy
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
    # Proxy: explicit override → per-provider (legacy) → GLOBAL Cloudflare proxy.
    g_url, g_secret = get_proxy_config(db)
    proxy_url = (
        payload.proxyUrl if payload.proxyUrl is not None
        else ((cfg.proxy_url if cfg else "") or g_url)
    ) or ""
    if payload.proxySecret not in (None, MASK):
        proxy_secret = payload.proxySecret
    elif cfg and cfg.proxy_secret_enc:
        proxy_secret = decrypt(cfg.proxy_secret_enc)
    else:
        proxy_secret = g_secret

    if not base:
        return _persist_test(db, cfg, "error", "Falta la URL base.", None)
    if not api_key:
        return _persist_test(db, cfg, "error", "Falta la clave de API.", None)

    # BCRD uses a different contract (token in the POST body, no proxy/WAF), so it
    # gets its own probe instead of the SIB Azure-APIM path below.
    if payload.provider == "bcrd":
        return _test_bcrd_connection(db, cfg, base, api_key)
    if payload.provider == "jurisai":
        return _test_jurisai_connection(db, cfg, base, api_key)

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


# ── PayPal (pasarela de pago, Fase 3 de monetización) ──────────────────
# Credenciales de la app PayPal Developer del comercio. Guardadas como AppSettings
# (client_id/secret encriptados; webhook_id/env/enabled en claro). El adaptador las lee
# con ``get_paypal_config``; la UI de admin las escribe (secretos preservados ante MASK).
_PP_CLIENT_ID = "paypal_client_id"
_PP_SECRET = "paypal_secret"
_PP_WEBHOOK_ID = "paypal_webhook_id"
_PP_ENV = "paypal_env"          # "sandbox" | "live"
_PP_ENABLED = "paypal_enabled"  # "1" | "0"
# Mapa de billing plans de PayPal por (sku, intervalo), JSON: {sku: {interval: plan_id}}.
# La suscripción v2 es por-sector con periodicidad, así que cada (insight:{sector}|all_access|
# enterprise, monthly|annual) que se venda necesita su plan de PayPal creado y mapeado acá.
_PP_PLANS = "paypal_plans"
# Mapa de Products de PayPal por SKU, JSON: {sku: product_id}. Un plan de PayPal cuelga de
# un Product; el sync automático (shared/billing/plan_sync) los crea una vez y los reutiliza
# al rotar precios.
_PP_PRODUCTS = "paypal_plan_products"


def _paypal_plans_map(db: Session) -> Dict[str, Dict[str, str]]:
    import json

    row = _get_app_setting(db, _PP_PLANS)
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return {}


def get_paypal_products(db: Session) -> Dict[str, str]:
    """Mapa {sku: product_id de PayPal} para el sync de billing plans."""
    import json

    row = _get_app_setting(db, _PP_PRODUCTS)
    if not row or not row.value:
        return {}
    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_paypal_products(db: Session, products: Dict[str, str]) -> None:
    import json

    _set_app_setting(db, _PP_PRODUCTS, json.dumps(products or {}), is_secret=False)
    db.commit()


def get_paypal_config(db: Session) -> Dict[str, object]:
    """Config PayPal en CLARO para el adaptador. ``enabled`` True solo si está habilitado
    Y hay client_id + secret. Sin valores → deshabilitado (la superficie de checkout
    responde 'no configurado')."""
    def _plain(key: str) -> str:
        row = _get_app_setting(db, key)
        return decrypt(row.value) if (row and row.value) else ""

    def _clear(key: str) -> str:
        row = _get_app_setting(db, key)
        return (row.value or "") if row else ""

    client_id = _plain(_PP_CLIENT_ID)
    secret = _plain(_PP_SECRET)
    enabled = _clear(_PP_ENABLED) == "1" and bool(client_id) and bool(secret)
    env = _clear(_PP_ENV) or "sandbox"
    return {"client_id": client_id, "secret": secret,
            "webhook_id": _clear(_PP_WEBHOOK_ID), "env": env, "enabled": enabled,
            "plans": _paypal_plans_map(db)}


def paypal_config_masked(db: Session) -> Dict[str, object]:
    """Config PayPal para el endpoint de lectura: secretos ENMASCARADOS (nunca en claro)."""
    cfg = get_paypal_config(db)
    return {
        "clientId": MASK if cfg["client_id"] else "",
        "secret": MASK if cfg["secret"] else "",
        "webhookId": cfg["webhook_id"],
        "env": cfg["env"],
        "plans": cfg["plans"],  # mapa {sku: {interval: plan_id}} (no secreto)
        "enabled": _get_app_setting(db, _PP_ENABLED) is not None
                   and (_get_app_setting(db, _PP_ENABLED).value == "1"),
        "configured": bool(cfg["enabled"]),
        # Cobrar y RECIBIR EVENTOS son dos capacidades distintas: con client_id+secret se
        # cobra, pero sin webhook_id no se puede verificar un solo evento entrante — y ahí se
        # pierden renovaciones, bajas por impago y reembolsos, en silencio.
        "webhookReady": bool(str(cfg["webhook_id"] or "").strip()),
    }


def set_paypal_config(db: Session, *, client_id: Optional[str], secret: Optional[str],
                      webhook_id: Optional[str], env: Optional[str],
                      enabled: Optional[bool],
                      plans: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, object]:
    """Guarda la config PayPal. Un secreto None o == MASK preserva el actual (no lo pisa
    con la máscara). ``plans`` reemplaza el mapa de billing plans; None lo deja igual."""
    import json

    if client_id is not None and client_id != MASK:
        _set_app_setting(db, _PP_CLIENT_ID, client_id.strip(), is_secret=True)
    if secret is not None and secret != MASK:
        _set_app_setting(db, _PP_SECRET, secret.strip(), is_secret=True)
    if webhook_id is not None:
        _set_app_setting(db, _PP_WEBHOOK_ID, webhook_id.strip(), is_secret=False)
    if env is not None:
        nuevo_env = "live" if env == "live" else "sandbox"
        env_row = _get_app_setting(db, _PP_ENV)
        # Solo hay MUDANZA de entorno si ya había uno guardado. Sin fila previa esto es la
        # primera configuración: no hay planes de otro entorno que invalidar, y borrarlos
        # tiraría los que el admin está cargando justo ahora.
        env_previo = env_row.value if (env_row and env_row.value) else None
        _set_app_setting(db, _PP_ENV, nuevo_env, is_secret=False)
        if env_previo is not None and nuevo_env != env_previo and plans is None:
            # Los billing plans y products son POR ENTORNO: un plan de sandbox no existe en
            # live. Dejarlos mapeados al mudarse hacía que el checkout intentara cobrar contra
            # un plan inexistente. Se limpian para que `sync-plans` los recree en el entorno
            # nuevo. Si el admin manda un mapa en el MISMO request, ese mapa manda: es su
            # intención explícita para el entorno al que se muda.
            _set_app_setting(db, _PP_PLANS, json.dumps({}), is_secret=False)
            _set_app_setting(db, _PP_PRODUCTS, json.dumps({}), is_secret=False)
            logger.warning("PayPal cambió de entorno %s → %s: mapa de planes y products "
                           "limpiado (correr sync-plans).", env_previo, nuevo_env)
    if enabled is not None:
        _set_app_setting(db, _PP_ENABLED, "1" if enabled else "0", is_secret=False)
    if plans is not None:
        # Limpia entradas vacías antes de guardar.
        clean = {sku: {iv: pid for iv, pid in (ivs or {}).items() if pid}
                 for sku, ivs in plans.items()}
        clean = {sku: ivs for sku, ivs in clean.items() if ivs}
        _set_app_setting(db, _PP_PLANS, json.dumps(clean), is_secret=False)
    db.commit()
    return paypal_config_masked(db)


# ── Impuestos (ITBIS RD) — matriz fiscal SDQ configurable ──────────────
# El impuesto sobre la venta NO es una constante mágica en código: es config administrable
# (decisión del dueño 2026-07-09). Regla: ITBIS 18% a clientes de RD; exportación de
# servicios a cliente del exterior = exento (0%). El precio del tarifario (``Tariff.amount``)
# es el SUBTOTAL pre-impuesto; el impuesto se suma encima. Guardado como AppSettings (nada
# secreto). Lo lee ``shared/billing/tax.py`` para computar el desglose de cada cobro.
_TAX_ENABLED = "tax_enabled"          # "1" | "0" (si 0, todo cobro va sin impuesto)
_TAX_RATE = "tax_rate"                # porcentaje, p.ej. "18" (ITBIS RD)
_TAX_LABEL = "tax_label"              # etiqueta visible, p.ej. "ITBIS"
_TAX_HOME_COUNTRY = "tax_home_country"    # ISO-2 del país que tributa, p.ej. "DO"
_TAX_EXEMPT_FOREIGN = "tax_exempt_foreign"  # "1" | "0": exento a clientes fuera del home

# Defaults de la matriz fiscal RD (aplican si el admin no configuró nada).
TAX_DEFAULTS = {
    "enabled": True, "rate": "18", "label": "ITBIS",
    "home_country": "DO", "exempt_foreign": True,
}


def get_tax_config(db: Session) -> Dict[str, object]:
    """Config de impuesto en claro para el motor de cálculo. Con fallbacks a los defaults
    de la matriz fiscal RD, para que una instalación fresca cobre ITBIS correctamente sin
    tener que configurar nada."""
    def _val(key: str, default: str) -> str:
        row = _get_app_setting(db, key)
        return (row.value if (row and row.value not in (None, "")) else default)

    enabled_row = _get_app_setting(db, _TAX_ENABLED)
    enabled = TAX_DEFAULTS["enabled"] if enabled_row is None else (enabled_row.value == "1")
    exf_row = _get_app_setting(db, _TAX_EXEMPT_FOREIGN)
    exempt_foreign = TAX_DEFAULTS["exempt_foreign"] if exf_row is None else (exf_row.value == "1")
    return {
        "enabled": enabled,
        "rate": _val(_TAX_RATE, TAX_DEFAULTS["rate"]),
        "label": _val(_TAX_LABEL, TAX_DEFAULTS["label"]),
        "home_country": (_val(_TAX_HOME_COUNTRY, TAX_DEFAULTS["home_country"]) or "DO").upper(),
        "exempt_foreign": exempt_foreign,
    }


def set_tax_config(db: Session, *, enabled: Optional[bool] = None, rate: Optional[str] = None,
                   label: Optional[str] = None, home_country: Optional[str] = None,
                   exempt_foreign: Optional[bool] = None) -> Dict[str, object]:
    """Guarda la config de impuesto (admin). Sólo escribe los campos provistos."""
    if enabled is not None:
        _set_app_setting(db, _TAX_ENABLED, "1" if enabled else "0", is_secret=False)
    if rate is not None:
        _set_app_setting(db, _TAX_RATE, str(rate).strip(), is_secret=False)
    if label is not None:
        _set_app_setting(db, _TAX_LABEL, label.strip(), is_secret=False)
    if home_country is not None:
        _set_app_setting(db, _TAX_HOME_COUNTRY, home_country.strip().upper()[:2], is_secret=False)
    if exempt_foreign is not None:
        _set_app_setting(db, _TAX_EXEMPT_FOREIGN, "1" if exempt_foreign else "0", is_secret=False)
    db.commit()
    return get_tax_config(db)


# ── Emisor de la factura (datos fiscales de SDQ) ───────────────────────
# Datos del comercio que emite la factura. El RNC y la secuencia NCF (comprobante fiscal
# DGII) son datos que el dueño debe cargar; sin ellos la factura sale como comprobante
# interno (no válido como crédito fiscal). Guardados como AppSettings (no secretos).
_INV_ISSUER_NAME = "invoice_issuer_name"
_INV_ISSUER_RNC = "invoice_issuer_rnc"
_INV_ISSUER_ADDRESS = "invoice_issuer_address"
_INV_ISSUER_EMAIL = "invoice_issuer_email"

INVOICE_ISSUER_DEFAULTS = {
    # Razón social EXACTA como está registrada ante la DGII bajo el RNC 132945271 (confirmada
    # por el dueño 2026-08-16). El default anterior decía "SDQ Consulting Group, SRL" — con
    # 'Group' — y en un comprobante fiscal el nombre tiene que coincidir con el registro.
    "name": "SDQ Consulting, SRL",
    "rnc": "",  # el dueño lo carga (brecha de servicio hasta entonces)
    "address": "Santo Domingo, República Dominicana",
    "email": "facturacion@sdqconsulting.com.do",
}


def get_invoice_issuer(db: Session) -> Dict[str, str]:
    """Datos del emisor de la factura, con defaults de marca SDQ. ``rnc`` vacío se muestra
    como pendiente (brecha) y marca la factura como comprobante interno."""
    def _val(key: str, default: str) -> str:
        row = _get_app_setting(db, key)
        return (row.value if (row and row.value not in (None, "")) else default)

    return {
        "name": _val(_INV_ISSUER_NAME, INVOICE_ISSUER_DEFAULTS["name"]),
        "rnc": _val(_INV_ISSUER_RNC, INVOICE_ISSUER_DEFAULTS["rnc"]),
        "address": _val(_INV_ISSUER_ADDRESS, INVOICE_ISSUER_DEFAULTS["address"]),
        "email": _val(_INV_ISSUER_EMAIL, INVOICE_ISSUER_DEFAULTS["email"]),
    }


# ── Régimen fiscal activo (NCF impreso vs e-CF electrónico) ────────────
# SDQ está en la transición de la Ley 32-23: hoy emite NCF tradicional contra rangos
# autorizados; al habilitarse como Emisor Electrónico pasa a e-CF. Es UNA LLAVE, no dos
# caminos simultáneos: emitir por los dos regímenes numeraría dos veces la misma venta.
_FISCAL_REGIME = "fiscal_regime"


def get_fiscal_regime(db: Session) -> str:
    """Régimen con el que se numeran los comprobantes hoy: ``ncf`` (default) o ``ecf``."""
    from shared.billing.fiscal.types import REGIME_ECF, REGIME_NCF

    row = _get_app_setting(db, _FISCAL_REGIME)
    value = (row.value if (row and row.value) else "").strip().lower()
    return REGIME_ECF if value == REGIME_ECF else REGIME_NCF


def set_fiscal_regime(db: Session, regime: str) -> str:
    """Cambia el régimen activo (admin). Valida contra los regímenes conocidos."""
    from shared.billing.fiscal.types import spec_for

    spec = spec_for(regime)
    _set_app_setting(db, _FISCAL_REGIME, spec.regime, is_secret=False)
    db.commit()
    return spec.regime


def set_invoice_issuer(db: Session, *, name: Optional[str] = None, rnc: Optional[str] = None,
                       address: Optional[str] = None, email: Optional[str] = None) -> Dict[str, str]:
    """Guarda los datos del emisor (admin). Sólo escribe los campos provistos."""
    if name is not None:
        _set_app_setting(db, _INV_ISSUER_NAME, name.strip(), is_secret=False)
    if rnc is not None:
        _set_app_setting(db, _INV_ISSUER_RNC, rnc.strip(), is_secret=False)
    if address is not None:
        _set_app_setting(db, _INV_ISSUER_ADDRESS, address.strip(), is_secret=False)
    if email is not None:
        _set_app_setting(db, _INV_ISSUER_EMAIL, email.strip(), is_secret=False)
    db.commit()
    return get_invoice_issuer(db)
