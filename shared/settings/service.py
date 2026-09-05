"""Business logic for in-app settings + sector data-source API configuration.

Read paths return masked output (never plaintext secrets). Write paths preserve
existing secrets when the client sends the masked placeholder. Resolution helpers
(``get_sector_api_*``) decrypt on demand for the connectors/scheduler and fall
back to env-based defaults so a fresh deployment still works.
"""
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

from sqlalchemy.orm import Session

from shared.config.settings import settings as app_settings
from shared.settings.crypto import decrypt, encrypt
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.schemas import (
    SmtpOut,
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
# and (for the sources behind a WAF) the Cloudflare proxy. ``requires_key`` and
# ``needs_proxy`` son informativos para la UI: el proxy es GLOBAL y lo resuelve
# `get_proxy_config`, no esta bandera. Detrás de un WAF hay dos, medidos: el SIB
# y la CMF de Chile.
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
        # Chile para el boletín regional. Entra al catálogo por lo que DOCUMENTA: es la
        # segunda fuente detrás de un WAF, y eso no se deduce de ninguna parte.
        #
        # Medido, no supuesto: desde una IP de escritorio el emisor responde con sus códigos
        # propios (421 «API key no valida», 422 «no suministrada»); desde el datacenter
        # devolvía 500 con una página «Web Page Blocked!» de 39 KB. Va por el mismo proxy
        # Cloudflare que el SIB, que debe tener `api.cmfchile.cl` en su lista de destinos.
        #
        # La cuota es de 10.000 peticiones MENSUALES, así que la prueba de conexión consulta
        # la UF de un mes ya cerrado: lo más barato que confirma la credencial.
        "provider": "cmf_chile",
        "providerName": "Comisión para el Mercado Financiero (CMF Chile)",
        "apiName": "API de Información Financiera",
        "country": "CL",
        "sector": "banking",
        "baseUrl": "https://api.cmfchile.cl",
        "requires_key": True,
        "needs_proxy": True,
        "notes": ("Clave en el portal de la CMF (api.cmfchile.cl), cuota de 10.000 consultas "
                  "al mes. Requiere el proxy Cloudflare (WAF). La atribución que exige el "
                  "emisor incluye fuente Y enlace: no es CC BY 4.0."),
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
# Techo DIARIO de gasto del modelo, administrable en caliente. Vive acá y no solo en la
# variable de entorno porque el 2026-08-20 una tarea generó informes que nadie pidió por
# USD 127 en un día: bajar el techo requería un redeploy, que es exactamente el tiempo que
# no se tiene cuando el gasto está corriendo. Lo lee ``shared/llm/budget.py``.
# "" / sin fila = no configurado (manda el entorno). "0" = APAGADO a propósito por el admin;
# son estados distintos y confundirlos deja la plataforma sin techo creyendo que lo tiene.
_LLM_BUDGET_KEY = "llm_daily_budget_usd"
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


def _contador_de_gasto_compartido() -> bool:
    """¿El contador del gasto diario es compartido entre workers? (best-effort, nunca rompe
    la pantalla de Configuración: ante la duda declara NO compartido, que es el caso en que
    el techo hay que leerlo con cuidado)."""
    try:
        from shared.llm.budget import contador_compartido
        return contador_compartido()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo determinar si el contador de gasto es compartido",
                       exc_info=True)
        return False


def get_llm_daily_budget(db: Session) -> float:
    """Techo diario de gasto LLM en USD vigente: el de Configuración si el admin lo fijó,
    si no el del entorno (``LLM_DAILY_BUDGET_USD``). 0 = sin techo, a sabiendas.

    Un valor guardado ilegible NO se interpreta como 0: "no se entiende el techo" y "no hay
    techo" son cosas distintas, y tratar la primera como la segunda es quedarse sin corte
    justo cuando algo anda mal. Cae al valor del entorno.
    """
    row = _get_app_setting(db, _LLM_BUDGET_KEY)
    if row is None or row.value in (None, ""):
        return float(app_settings.LLM_DAILY_BUDGET_USD)
    try:
        return max(0.0, float(str(row.value)))
    except (TypeError, ValueError):
        logger.warning("Techo LLM guardado ilegible (%r): se usa el del entorno.", row.value)
        return float(app_settings.LLM_DAILY_BUDGET_USD)


def set_llm_daily_budget(db: Session, usd: float) -> float:
    """Fija el techo diario (admin). Negativo se rechaza; 0 apaga el corte a propósito."""
    valor = float(usd)
    if valor < 0:
        raise ValueError("El presupuesto diario no puede ser negativo. Use 0 para desactivarlo.")
    _set_app_setting(db, _LLM_BUDGET_KEY, f"{valor:.2f}", is_secret=False)
    db.commit()
    _invalidar_cache_de_techo()
    return get_llm_daily_budget(db)


def _invalidar_cache_de_techo() -> None:
    """El techo se memoriza unos segundos en el proceso que cobra (ver ``shared/llm/budget``).
    Sin esta invalidación, bajarlo desde Configuración tardaría ese TTL en morder — y se baja
    justo cuando el gasto ya está corriendo."""
    try:
        from shared.llm import budget
        budget.invalidate_limit_cache()
    except Exception:  # noqa: BLE001 — el guardado ya ocurrió; el TTL lo corrige solo
        logger.warning("No se pudo invalidar la caché del techo LLM", exc_info=True)


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
        llmDailyBudgetUsd=get_llm_daily_budget(db),
        llmBudgetCounterShared=_contador_de_gasto_compartido(),
        sectorApis=[_to_out(c) for c in apis],
        smtp=_smtp_out(db),
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
    if payload.llmDailyBudgetUsd is not None:
        if payload.llmDailyBudgetUsd < 0:
            raise ValueError(
                "El presupuesto diario no puede ser negativo. Use 0 para desactivarlo.")
        _set_app_setting(db, _LLM_BUDGET_KEY, f"{float(payload.llmDailyBudgetUsd):.2f}",
                         is_secret=False)
        _invalidar_cache_de_techo()
    if payload.sectorApis is not None:
        for api in payload.sectorApis:
            _upsert_sector_api(db, api)
    if payload.smtp is not None:
        m = payload.smtp
        # MASK significa «no la toques»: la pantalla nunca recibe la contraseña guardada, así
        # que reenvía el placeholder. Sin este filtro, guardar el remitente borraría la llave.
        clave = None if (m.password is None or m.password == MASK) else m.password
        set_smtp_config(db, host=m.host, port=m.port, user=m.user, password=clave,
                        remitente=m.fromAddress, starttls=m.starttls)
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


#: Lo que se le dice al operador cuando el bloqueo es del WAF y no del emisor. Vive acá y no
#: incrustado en la llamada porque un literal largo se parte por ancho de línea y la frase
#: deja de existir en el fuente: el test que la vigila fallaría sin que nada esté mal.
MSG_WAF_BLOQUEO = ("Un WAF bloqueó la petición antes de llegar a la CMF{ip}. "
                   "La credencial no se llegó a evaluar{consejo}")
MSG_WAF_SIN_PROXY = "; configurá el proxy para esta fuente, como el SIB."
#: Cuando el 500 lo devuelve el WORKER y no el emisor. El Worker marca todo lo que REENVÍA
#: con `X-Proxy-Status`; su ausencia en un error significa que nunca llegó a la CMF.
MSG_PROXY_NO_REENVIO = ("El proxy no reenvió la petición a la CMF (respondió {codigo} sin "
                        "marca de reenvío). Suele ser que el Worker solo permite el dominio "
                        "del SIB: hay que habilitar api.cmfchile.cl en su lista.")


def _redactar(texto: str) -> str:
    """Saca la credencial de cualquier texto que vaya a mostrarse.

    Los cuerpos de error repiten la URL consultada, y esa URL lleva la `apikey` en la query
    string. Un diagnóstico que ayuda no puede filtrar la clave a la pantalla.
    """
    return re.sub(r"(apikey=)[^&\s\"'<]+", r"\1«REDACTADA»", texto or "")


def _test_cmf_connection(db, cfg, base: str, api_key: str,
                         proxy_url: Any = "", proxy_secret: Any = "") -> TestConnectionOut:
    """Prueba contra la API de la CMF de Chile, que tiene un contrato propio.

    Nada del camino del SIB sirve acá: la CMF pide la credencial en la QUERY STRING
    (`?apikey=…&formato=json`), no en un header de suscripción de Azure APIM. Sin esta rama,
    la prueba armaba
    `api.cmfchile.cl/indicadores/principales` —una ruta del emisor dominicano— y devolvía
    «HTTP 500 (SIB)»: un error que hace revisar la clave cuando lo que estaba mal era el
    emisor contra el que se probaba.

    **Sí está detrás de un WAF**, contra lo que decía la primera versión de esta función.
    Medido: desde una IP de escritorio el emisor responde con sus códigos propios —421 «API
    key no valida», 422 «no suministrada»— y desde el datacenter devolvía 500 con una página
    «Web Page Blocked!». Es el mismo obstáculo que el SIB, así que se reusa el mismo proxy.

    Se consulta la UF y no un reporte bancario a propósito. La cuota es de 10.000 peticiones
    MENSUALES (lo dice el emisor en «Uso de la API Key»), así que la prueba tiene que costar
    lo mínimo; y un cuadro de adecuación de capital de un mes concreto puede no estar
    publicado todavía y haría fallar una credencial que está perfecta.
    """
    import httpx

    # Con PERÍODO explícito. La ruta pelada `/uf` existe lo suficiente para rechazar la
    # falta de credencial con 422, pero con una clave VÁLIDA entra a la lógica y devuelve
    # 500: la documentación del emisor no ofrece ninguna forma sin fecha —todas son
    # `/uf/<año>`, `/uf/<año>/<mes>`, `/uf/<año>/<mes>/dias/<día>`—. El síntoma engaña,
    # porque el 500 aparece justo cuando la credencial es correcta.
    #
    # El período es FIJO y pasado a propósito: un mes ya cerrado siempre tiene dato, así que
    # la prueba mide la credencial y no la frescura de la fuente. Con el mes en curso, una
    # clave perfecta podría fallar un día 1.
    target = f"{base.rstrip('/')}/api-sbifv3/recursos_api/uf/2024/01"
    url = f"{target}?apikey={api_key}&formato=json"
    # El proxy llega del resolvedor general, que lo arma de tres orígenes posibles (override
    # del formulario, columna de la fila, proxy global), así que su tipo es laxo.
    proxy_url, proxy_secret = str(proxy_url or ""), str(proxy_secret or "")
    use_proxy = bool(proxy_url and proxy_secret)
    try:
        if use_proxy:
            resp = httpx.post(
                f"{proxy_url.rstrip('/')}/proxy",
                json={"url": url, "headers": {"Accept": "application/json"}, "method": "GET"},
                headers={"X-Proxy-Secret": proxy_secret, "Content-Type": "application/json"},
                timeout=30)
        else:
            resp = httpx.get(url, timeout=25, follow_redirects=True)
    except httpx.HTTPError as e:
        return _persist_test(db, cfg, "error",
                             f"No se pudo alcanzar {base} ({type(e).__name__}).", None)
    # Se BUSCA en el cuerpo entero y se MUESTRA un extracto. Recortar antes de analizar fue
    # el defecto: la página del WAF mide 39.142 caracteres y su marca —«Web Page Blocked»,
    # con la IP que vio— está en la posición 38.821, así que buscarla en los primeros 500
    # la perdía siempre. Lo único que quedaba a la vista era el DOCTYPE, y el diagnóstico
    # decía «la CMF respondió 500» sobre una petición que nunca llegó a la CMF.
    cuerpo_completo = resp.text or ""
    cuerpo_txt = cuerpo_completo[:500]
    if use_proxy and resp.status_code >= 400 and not _has_proxy_relay(resp):
        # El Worker rechazó: la petición nunca salió hacia la CMF, así que ni la credencial
        # ni el WAF del emisor tuvieron nada que ver.
        return _persist_test(db, cfg, "error",
                             MSG_PROXY_NO_REENVIO.format(codigo=resp.status_code),
                             resp.status_code)
    if "Web Page Blocked" in cuerpo_completo or "has been blocked" in cuerpo_completo:
        # El WAF, no la CMF. Distinguirlo importa: un «500» pelado manda a revisar la
        # credencial, y acá la credencial ni siquiera llegó a evaluarse.
        m = re.search(r"Client IP:\s*([0-9.]+)", cuerpo_completo)
        ip = f" (IP vista por el WAF: {m.group(1)})" if m else ""
        return _persist_test(
            db, cfg, "error",
            MSG_WAF_BLOQUEO.format(ip=ip, consejo="." if use_proxy else MSG_WAF_SIN_PROXY),
            resp.status_code)
    if resp.status_code == 422:
        # El emisor usa 422 —no 401— para «API key no ha sido suministrada» y también para
        # una clave inválida. Se reporta lo que dice, sin adivinar cuál de las dos fue.
        return _persist_test(db, cfg, "error",
                             "La CMF rechazó la credencial (422). Revisá que la clave esté "
                             "cargada y vigente.", 422)
    if resp.status_code >= 400:
        # Los códigos propios del emisor: 421 «API key no valida», 420 cuota superada. Se
        # transcribe SU mensaje en vez de traducir un HTTP genérico a una conjetura nuestra.
        detalle = ""
        try:
            j = resp.json()
            if isinstance(j, dict) and j.get("Mensaje"):
                detalle = f' — la CMF dice: "{str(j["Mensaje"])[:120]}"'
        except ValueError:
            pass
        if not detalle and cuerpo_txt.strip():
            # Sin cuerpo interpretable, se muestra un extracto CRUDO. Tres vueltas se
            # perdieron mostrando solo el número de HTTP mientras la respuesta traía la
            # explicación: un diagnóstico que descarta la evidencia no es un diagnóstico.
            extracto = " ".join(_redactar(cuerpo_txt).split())[:160]
            detalle = f" — respondió: {extracto}"
        return _persist_test(db, cfg, "error",
                             f"La CMF respondió HTTP {resp.status_code}{detalle}.",
                             resp.status_code)
    try:
        cuerpo = resp.json()
    except ValueError:
        return _persist_test(db, cfg, "error",
                             "La CMF respondió algo que no es JSON.", resp.status_code)
    if not isinstance(cuerpo, dict) or not cuerpo:
        return _persist_test(db, cfg, "error",
                             "La CMF respondió un cuerpo vacío o inesperado.",
                             resp.status_code)
    return _persist_test(db, cfg, "success",
                         "Conexión con la CMF de Chile verificada (UF).", resp.status_code)


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
    # Proxy: override CON CONTENIDO → per-provider (legacy) → GLOBAL Cloudflare proxy.
    #
    # Una cadena VACÍA no es un override. `proxy_url` es NOT NULL DEFAULT '' y el editor por
    # fuente ya no tiene campo de proxy —pasó a ser global—, pero el formulario igual arrastra
    # el valor de la fila y lo manda en cada prueba. Leerlo como «probá sin proxy» dejaba el
    # proxy global sin usar: la petición salía directa y el WAF de la CMF la cortaba con la
    # credencial correcta, mostrando un bloqueo que no era culpa de la clave. Ninguna casilla
    # de la interfaz significa «sin proxy», así que `""` solo puede querer decir «esta fila no
    # tiene proxy propio». El SIB no lo destapó porque su fila conserva el proxy de antes de
    # la migración a global, y ganaba por herencia.
    g_url, g_secret = get_proxy_config(db)
    proxy_url = payload.proxyUrl or (cfg.proxy_url if cfg else "") or g_url or ""
    if payload.proxySecret and payload.proxySecret != MASK:
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
    if payload.provider == "cmf_chile":
        return _test_cmf_connection(db, cfg, base, api_key, proxy_url, proxy_secret)

    # De acá para abajo es el contrato del SIB —Azure APIM con subscription-key + un WAF
    # de Sucuri que bloquea IPs de datacenter, de ahí la UA de Mozilla y el proxy en prod—.
    # NO es un camino genérico: un proveedor sin rama propia termina probándose contra las
    # rutas del emisor dominicano, y el error que ve el operador lleva la etiqueta «SIB».
    # Pasó con la CMF de Chile: «HTTP 500 (SIB)» mandaba a revisar una clave que estaba
    # perfecta. Si agregás una fuente nueva con otro contrato, agregale su rama arriba.
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
        if use_proxy and not relayed:
            origin = "proxy Cloudflare"
        elif payload.provider == "sb_do":
            origin = "SIB"
        else:
            # Se prueba con el contrato del SIB porque no hay rama para este proveedor: el
            # error es de esa ruta, no del emisor que el operador cree estar probando.
            origin = f"{payload.provider} probado con el contrato del SIB — falta su rama"
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


# ── Correo saliente (SMTP) ────────────────────────────────────────
# Vive acá y no sólo en el entorno por la misma razón que el techo de gasto: mover el canal
# de correo por variable de entorno exige un redeploy, y el dueño de la instalación no
# necesariamente tiene acceso al panel de infraestructura. La contraseña es un SECRETO y va
# cifrada con Fernet, igual que la llave de Claude — nunca vuelve al cliente en claro.
_SMTP_HOST = "smtp_host"
_SMTP_PORT = "smtp_port"
_SMTP_USER = "smtp_user"
_SMTP_PASSWORD = "smtp_password"
_SMTP_FROM = "smtp_from"
_SMTP_STARTTLS = "smtp_starttls"


def _smtp_guardado(db: Session, key: str) -> Optional[str]:
    """Valor guardado para *key*, o ``None`` si NO hay fila.

    La distinción importa: **si hay fila, manda la fila, aunque esté vacía.** Vaciar el host
    desde Configuración es la forma de APAGAR el canal, y caer al entorno en ese caso lo
    resucitaría sin que nadie lo pida. Sólo la ausencia de fila delega en el entorno.
    """
    row = _get_app_setting(db, key)
    if row is None:
        return None
    if row.is_secret and row.value:
        return decrypt(str(row.value))
    return str(row.value or "")


def get_smtp_config(db: Session) -> Dict[str, Any]:
    """Configuración de correo vigente: la de Configuración si está, si no la del entorno.

    Devuelve la contraseña en claro porque el ÚNICO consumidor es el emisor
    (``shared/notifications/email``). La superficie HTTP nunca la sirve: ver
    :func:`get_smtp_public`.
    """
    def _v(key: str, env: str) -> str:
        guardado = _smtp_guardado(db, key)
        return guardado if guardado is not None else str(env or "")

    puerto_txt = _v(_SMTP_PORT, str(app_settings.SMTP_PORT))
    try:
        puerto = int(puerto_txt or 0) or 587
    except (TypeError, ValueError):
        # Un puerto ilegible NO se interpreta como "sin correo": se usa el estándar de
        # STARTTLS y se deja rastro. Confundir "no se entiende" con "no hay" apaga el canal
        # justo cuando alguien acaba de intentar encenderlo.
        logger.warning("Puerto SMTP guardado ilegible (%r): se usa 587.", puerto_txt)
        puerto = 587

    starttls_txt = _smtp_guardado(db, _SMTP_STARTTLS)
    starttls = (bool(app_settings.SMTP_STARTTLS) if starttls_txt is None
                else starttls_txt.strip().lower() in ("1", "true", "yes", "on", "si", "sí"))

    return {
        "host": _v(_SMTP_HOST, app_settings.SMTP_HOST).strip(),
        "port": puerto,
        "user": _v(_SMTP_USER, app_settings.SMTP_USER).strip(),
        "password": _v(_SMTP_PASSWORD, app_settings.SMTP_PASSWORD),
        "from": _v(_SMTP_FROM, app_settings.SMTP_FROM).strip(),
        "starttls": starttls,
    }


def get_smtp_public(db: Session) -> Dict[str, Any]:
    """Forma que SÍ puede cruzar la API: la contraseña sale como booleano, nunca su valor.

    Un campo de contraseña que devuelve su contenido es una filtración con formulario."""
    cfg = get_smtp_config(db)
    return {
        "host": cfg["host"], "port": cfg["port"], "user": cfg["user"],
        "from": cfg["from"], "starttls": cfg["starttls"],
        "password_set": bool(cfg["password"]),
    }


def set_smtp_config(db: Session, *, host: Optional[str] = None, port: Optional[int] = None,
                    user: Optional[str] = None, password: Optional[str] = None,
                    remitente: Optional[str] = None,
                    starttls: Optional[bool] = None) -> Dict[str, Any]:
    """Guarda la configuración de correo (admin). Sólo escribe los campos provistos.

    ``password`` sigue una regla propia: ``None`` significa «no la toques» y ``""`` significa
    «borrala». Sin esa distinción, cualquier guardado de la pantalla —que nunca recibe la
    contraseña actual— borraría la llave al reenviar el formulario.
    """
    if host is not None:
        _set_app_setting(db, _SMTP_HOST, host.strip(), is_secret=False)
    if port is not None:
        _set_app_setting(db, _SMTP_PORT, str(int(port)), is_secret=False)
    if user is not None:
        _set_app_setting(db, _SMTP_USER, user.strip(), is_secret=False)
    if password is not None:
        _set_app_setting(db, _SMTP_PASSWORD, password.strip(), is_secret=True)
    if remitente is not None:
        _set_app_setting(db, _SMTP_FROM, remitente.strip(), is_secret=False)
    if starttls is not None:
        _set_app_setting(db, _SMTP_STARTTLS, "true" if starttls else "false", is_secret=False)
    db.commit()
    _invalidar_cache_de_correo()
    return get_smtp_public(db)


def _invalidar_cache_de_correo() -> None:
    """El emisor memoriza la configuración unos segundos para no consultar la base en cada
    entrega de un barrido. Sin esta invalidación, encender el correo desde Configuración
    tardaría ese TTL en surtir efecto — y el botón «enviar prueba» diría que no hay canal
    justo después de que el admin acaba de configurarlo."""
    try:
        from shared.notifications import email as mail
        mail.invalidar_cache()
    except Exception:  # noqa: BLE001 — el guardado ya ocurrió; el TTL lo corrige solo
        logger.warning("No se pudo invalidar la caché de correo", exc_info=True)


def _smtp_out(db: Session) -> SmtpOut:
    """Bloque de correo para la pantalla. ``configurado`` y ``falta`` los computa el EMISOR,
    no esta función: si la pantalla dedujera por su cuenta que «hay host ⇒ hay canal», el día
    que el emisor agregue una condición la pantalla seguiría diciendo que sí. Una sola
    autoridad sobre si el canal existe."""
    from shared.notifications import email as mail

    pub = get_smtp_public(db)
    diag = mail.diagnostico(db)
    return SmtpOut(
        host=str(pub["host"]), port=int(pub["port"]), user=str(pub["user"]),
        fromAddress=str(pub["from"]), starttls=bool(pub["starttls"]),
        passwordSet=bool(pub["password_set"]),
        configurado=bool(diag["configurado"]), falta=list(diag["falta"]),
    )


def probar_smtp(db: Session, destinatario: str) -> Dict[str, str]:
    """Manda un correo de prueba REAL y devuelve el motivo si falla.

    Es la única forma honesta de responder «¿quedó bien configurado?». Un endpoint que
    valide el formulario y responda 200 confirma que el formulario está completo, que es una
    pregunta distinta —y menos útil— que si el correo sale.
    """
    from shared.notifications import email as mail

    ok, motivo = mail.enviar_o_motivo(
        destinatario,
        "SDQ·MIP — prueba de correo saliente",
        "Este es un correo de prueba de SDQ·MIP.\n\n"
        "Si lo estás leyendo, el canal de correo quedó configurado y las alertas de tus "
        "vigilancias van a llegar por acá.\n",
        db=db)
    return {"status": "success" if ok else "error", "detail": motivo,
            "destinatario": destinatario}
