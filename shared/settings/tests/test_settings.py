"""Tests for the in-app settings + sector data-source config service and API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.settings import service
from shared.settings.crypto import decrypt, encrypt
from shared.settings.models import AppSetting, SectorApiConfig
from shared.settings.router import router as settings_router
from shared.settings.schemas import (
    MASK,
    SectorApiIn,
    SettingsIn,
    TestConnectionIn as ConnTestIn,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection so TestClient's thread sees the tables
    )
    Base.metadata.create_all(engine, tables=[AppSetting.__table__, SectorApiConfig.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── crypto ────────────────────────────────────────────────────────
def test_crypto_roundtrip():
    assert decrypt(encrypt("super-secret-key")) == "super-secret-key"


def test_crypto_empty_and_bad():
    assert encrypt("") == ""
    assert decrypt("") == ""
    assert decrypt("not-a-valid-token") == ""  # never raises


def test_ciphertext_is_not_plaintext():
    assert "super-secret" not in encrypt("super-secret")


# ── service: claude key ───────────────────────────────────────────
def test_claude_key_stored_encrypted(db):
    service.update_settings(db, SettingsIn(claudeApiKey="sk-ant-123"))
    row = db.query(AppSetting).filter(AppSetting.key == "claude_api_key").first()
    assert row is not None
    assert row.value != "sk-ant-123"  # encrypted at rest
    assert service.get_claude_api_key(db) == "sk-ant-123"
    out = service.get_settings(db)
    assert out.claudeApiKeySet is True


# ── service: sector apis ──────────────────────────────────────────
def test_sector_api_upsert_and_masking(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", providerName="SB", apiKey="primary-key", baseUrl="https://x"),
    ]))
    out = service.get_settings(db)
    api = next(a for a in out.sectorApis if a.provider == "sb_do")
    assert api.apiKeySet is True
    assert api.apiKeyMasked == MASK
    # The plaintext key is never returned by the API model.
    assert "primary-key" not in api.model_dump_json()


def test_masked_key_preserved_on_update(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="real-key"),
    ]))
    # Re-save sending the mask (as the UI does) → key must be kept.
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey=MASK, providerName="Updated"),
    ]))
    assert service.get_sector_api_key(db, "sb_do") == "real-key"
    assert service.get_settings(db).sectorApis[0].providerName == "Updated"


def test_empty_string_clears_key(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="k")]))
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="")]))
    assert service.get_sector_api_key(db, "sb_do") == ""


def test_resolution_helpers(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="k1", apiKeySecondary="k2",
                    baseUrl="https://apis.sb.gob.do/estadisticas/v2",
                    proxyUrl="https://w.workers.dev", proxySecret="psecret"),
    ]))
    assert service.get_sector_api_key(db, "sb_do") == "k1"
    assert service.get_sector_api_key_secondary(db, "sb_do") == "k2"
    assert service.get_sector_api_base_url(db, "sb_do").endswith("/estadisticas/v2")
    assert service.get_sector_api_proxy(db, "sb_do") == ("https://w.workers.dev", "psecret")


def test_find_banking_source_by_sector_not_id(db):
    """A provider with an arbitrary id but sector=banking is still resolved."""
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="SDQFinAnalyst", sector="banking", country="DO",
        apiKey="sib-real-key", baseUrl="https://apis.sb.gob.do/estadisticas/v2",
    )]))
    cfg = service.find_banking_source(db)
    assert cfg is not None and cfg.provider == "SDQFinAnalyst"
    creds = service.get_sib_credentials(db)
    assert creds["api_key"] == "sib-real-key"
    assert creds["base_url"].endswith("/estadisticas/v2")


def test_find_banking_source_prefers_sb_do(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="Other", sector="banking", country="DO", apiKey="k-other"),
        SectorApiIn(provider="sb_do", sector="banking", country="DO", apiKey="k-canonical"),
    ]))
    assert service.find_banking_source(db).provider == "sb_do"
    assert service.get_sib_credentials(db)["api_key"] == "k-canonical"


def test_find_banking_source_ignores_disabled(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="SDQFinAnalyst", sector="banking", country="DO", apiKey="k", enabled=False,
    )]))
    assert service.find_banking_source(db) is None


def test_find_banking_source_skips_non_banking(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="trade_x", sector="trade", country="DO", apiKey="k",
    )]))
    assert service.find_banking_source(db) is None


def test_disabled_provider_hides_key(db):
    service.update_settings(db, SettingsIn(sectorApis=[
        SectorApiIn(provider="sb_do", apiKey="k1", enabled=False),
    ]))
    # Disabled → resolution falls back (env empty here) instead of returning the key.
    assert service.get_sector_api_key(db, "sb_do") == ""


def test_ensure_known_sources_seeds_catalog(db):
    n = service.ensure_known_sources(db)
    assert n >= 4  # bcrd, one_do, comtrade, wgi (+ sb_do if no banking yet)
    out = service.get_settings(db)
    sectors = {a.sector for a in out.sectorApis}
    assert {"macro", "social", "trade", "governance"} <= sectors
    # Seeded sources are disabled (no keys) until the operator fills them.
    bcrd = next(a for a in out.sectorApis if a.provider == "bcrd")
    assert bcrd.enabled is False and bcrd.apiKeySet is False
    assert bcrd.baseUrl == "https://api.bancentral.gov.do"


def test_ensure_known_sources_idempotent(db):
    service.ensure_known_sources(db)
    before = len(service.get_settings(db).sectorApis)
    service.ensure_known_sources(db)
    after = len(service.get_settings(db).sectorApis)
    assert before == after


def test_ensure_known_sources_skips_existing_sector(db):
    # Operator already has a banking source under a custom id.
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="SDQFinAnalyst", sector="banking", country="DO", apiKey="k",
    )]))
    service.ensure_known_sources(db)
    providers = {a.provider for a in service.get_settings(db).sectorApis}
    assert "sb_do" not in providers  # not duplicated
    assert "SDQFinAnalyst" in providers


def test_delete_sector_api(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(provider="sb_do", apiKey="k")]))
    assert service.delete_sector_api(db, "sb_do") is True
    assert service.delete_sector_api(db, "sb_do") is False


def test_connection_test_requires_key(db):
    res = service.test_connection(db, ConnTestIn(provider="sb_do", baseUrl="https://x", apiKey=""))
    assert res.status == "error"


class _FakeResp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def _proxy_provider(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="sb_do", apiKey="sib-key", baseUrl="https://apis.sb.gob.do/estadisticas/v2",
        proxyUrl="https://w.workers.dev", proxySecret="psecret",
    )]))


def test_proxy_secret_invalid_is_distinguished(db, monkeypatch):
    """401 with NO X-Proxy-Status header → the Worker rejected the proxy secret."""
    import httpx
    _proxy_provider(db)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(401, {}))
    res = service.test_connection(db, ConnTestIn(provider="sb_do"))
    assert res.status == "error"
    assert "proxy" in res.detail.lower()
    assert "sib" not in res.detail.lower()


def test_sib_key_invalid_is_distinguished(db, monkeypatch):
    """401 WITH X-Proxy-Status → the proxy relayed the SIB's rejection (bad SIB key)."""
    import httpx
    _proxy_provider(db)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(401, {"X-Proxy-Status": "401"}))
    res = service.test_connection(db, ConnTestIn(provider="sb_do"))
    assert res.status == "error"
    assert "sib" in res.detail.lower()


def test_proxy_success(db, monkeypatch):
    import httpx
    _proxy_provider(db)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(200, {"X-Proxy-Status": "200"}))
    res = service.test_connection(db, ConnTestIn(provider="sb_do"))
    assert res.status == "success"
    assert res.viaProxy is True


# ── BCRD: provider-aware probe (token in body, no proxy) ──────────
def _bcrd_provider(db):
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="bcrd", apiKey="bcrd-token", baseUrl="https://api.bancentral.gov.do",
    )]))


def test_bcrd_uses_own_probe_not_sib(db, monkeypatch):
    """BCRD test posts the token to MacroVariables — never the SIB indicadores path."""
    from shared.data import bcrd_api
    captured = {}

    def _fake_fetch(token, variable, base_url=None, timeout=30):
        captured["token"] = token
        captured["variable"] = variable
        captured["base_url"] = base_url
        return {"name": "Inflación", "values": [{"period": "2025-01", "value": 4.5}]}

    monkeypatch.setattr(bcrd_api, "fetch_bcrd_variable", _fake_fetch)
    _bcrd_provider(db)
    res = service.test_connection(db, ConnTestIn(provider="bcrd"))
    assert res.status == "success"
    assert res.viaProxy is False
    assert captured["token"] == "bcrd-token"
    assert captured["variable"] == "inflacion"
    assert captured["base_url"] == "https://api.bancentral.gov.do"


def test_bcrd_invalid_token_is_distinguished(db, monkeypatch):
    import httpx
    from shared.data import bcrd_api

    class _Resp:
        status_code = 401

    def _fake_fetch(*a, **k):
        raise httpx.HTTPStatusError("401", request=None, response=_Resp())

    monkeypatch.setattr(bcrd_api, "fetch_bcrd_variable", _fake_fetch)
    _bcrd_provider(db)
    res = service.test_connection(db, ConnTestIn(provider="bcrd"))
    assert res.status == "error"
    assert "token" in res.detail.lower()
    assert "sib" not in res.detail.lower()
    assert res.viaProxy is False


def test_bcrd_rejected_token_surfaces_message(db, monkeypatch):
    """A rejected token comes back as an ABP app error → clear, token-specific msg."""
    from shared.data import bcrd_api

    def _fake_fetch(*a, **k):
        raise bcrd_api.BcrdApiError("Credenciales de acceso inválidas", is_auth=True)

    monkeypatch.setattr(bcrd_api, "fetch_bcrd_variable", _fake_fetch)
    _bcrd_provider(db)
    res = service.test_connection(db, ConnTestIn(provider="bcrd"))
    assert res.status == "error"
    assert "Credenciales de acceso inválidas" in res.detail
    assert "rechazado" in res.detail.lower()


# ── router RBAC ───────────────────────────────────────────────────
def _client(db, role):
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/v1/settings")

    class _U:
        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def test_admin_can_read(db):
    r = _client(db, UserRole.admin).get("/api/v1/settings")
    assert r.status_code == 200
    assert "sectorApis" in r.json()


@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.analyst])
def test_non_admin_forbidden(db, role):
    c = _client(db, role)
    assert c.get("/api/v1/settings").status_code == 403
    assert c.put("/api/v1/settings", json={}).status_code == 403


def test_global_cloudflare_proxy_set_and_resolved(db):
    """The proxy is a single global credential (like the Claude key)."""
    from shared.settings.schemas import SettingsIn
    service.update_settings(db, SettingsIn(
        cloudflareProxyUrl="https://proxy.example.workers.dev",
        cloudflareProxySecret="s3cr3t",
    ))
    out = service.get_settings(db)
    assert out.cloudflareProxyUrl == "https://proxy.example.workers.dev"
    assert out.cloudflareProxySecretSet is True
    # The secret is never echoed back; resolution returns it for connectors.
    url, secret = service.get_proxy_config(db)
    assert url == "https://proxy.example.workers.dev" and secret == "s3cr3t"
    # SIB credentials now resolve the proxy from the global setting.
    creds = service.get_sib_credentials(db)
    assert creds["proxy_url"] == "https://proxy.example.workers.dev"
    assert creds["proxy_secret"] == "s3cr3t"


def test_per_provider_proxy_migrates_to_global(db):
    """An existing SIB per-config proxy is copied to the global setting once."""
    from shared.settings.schemas import SectorApiIn, SettingsIn
    service.update_settings(db, SettingsIn(sectorApis=[SectorApiIn(
        provider="sb_do", sector="banking", baseUrl="https://apis.sb.gob.do",
        apiKey="k", proxyUrl="https://old-proxy.workers.dev", proxySecret="oldsecret",
    )]))
    service._migrate_proxy_to_global(db)
    url, secret = service.get_proxy_config(db)
    assert url == "https://old-proxy.workers.dev" and secret == "oldsecret"


def test_needs_secondary_flag(db):
    """SIB (Azure APIM) needs a secondary key; BCRD (single token) does not."""
    out = service.get_settings(db)
    by_provider = {a.provider: a for a in out.sectorApis}
    assert by_provider["sb_do"].needsSecondary is True
    assert by_provider["bcrd"].needsSecondary is False


def test_jurisai_aparece_en_configuracion_para_que_el_dueno_coloque_su_clave():
    """El eje de evaluación de leyes necesita la clave de JurisAI, y la pantalla de
    Configuración se arma sola desde `KNOWN_PROVIDERS`: alcanza con declararlo ahí.

    Se comprueba también que la URL base venga VACÍA. Una por defecto que estuviera mal
    haría fallar la prueba de conexión culpando a la clave, que es el diagnóstico más caro
    de perseguir.
    """
    from shared.settings.service import KNOWN_PROVIDERS

    j = next((p for p in KNOWN_PROVIDERS if p["provider"] == "jurisai"), None)
    assert j is not None, "JurisAI no aparecería en la pantalla de Configuración"
    assert j["requires_key"] is True
    # La advertencia de fragilidad del dominio DESAPARECIÓ porque su causa desapareció: el
    # emisor migró a `api.jurisai.do`, un dominio propio, el 2026-08-19. Lo que se comprueba
    # ahora es lo que la reemplaza — que el default apunte al dominio del emisor y que el
    # host retirado quede DECLARADO, que es lo único que permite migrar las instalaciones
    # que ya existen. Sigue siendo editable, para un proxy o un entorno de prueba.
    assert j["baseUrl"] == "https://api.jurisai.do/api/v1"
    assert j["obsoleteBaseUrls"], (
        "sin declarar el host retirado, las instalaciones existentes se quedan apuntando "
        "ahí para siempre: el host viejo responde 200 y nada avisa")
    assert j["sector"] == "law"


def test_la_clave_de_jurisai_se_guarda_CIFRADA_y_no_vuelve_en_claro(db):
    """Es una credencial de un tercero: si la pantalla la devolviera en claro, quedaría en
    el historial del navegador y en cualquier registro de red."""
    import json

    from shared.settings.models import SectorApiConfig
    from shared.settings.service import _upsert_sector_api, get_sector_api_key, get_settings
    from shared.settings.schemas import SectorApiIn

    _upsert_sector_api(db, SectorApiIn(
        provider="jurisai", baseUrl="https://api.jurisai.example", apiKey="SECRETO-123"))
    db.commit()

    fila = db.query(SectorApiConfig).filter_by(provider="jurisai").first()
    assert fila is not None and fila.api_key_enc
    assert "SECRETO-123" not in (fila.api_key_enc or ""), "la clave quedó en claro en la base"
    assert get_sector_api_key(db, "jurisai") == "SECRETO-123", "el conector no la recupera"

    servido = get_settings(db)
    assert "SECRETO-123" not in json.dumps(servido, default=str), "la clave se devolvió al cliente"


# ── service: techo diario de gasto del modelo ─────────────────────
# El 2026-08-20 una tarea generó informes que nadie pidió por USD 127 en un día. El techo
# existía en código pero solo se podía mover por variable de entorno, o sea con un redeploy:
# justo el tiempo que no se tiene cuando el gasto ya está corriendo.

def test_sin_configurar_el_techo_es_el_del_entorno(db, monkeypatch):
    from shared.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)
    assert service.get_llm_daily_budget(db) == 25.0
    assert service.get_settings(db).llmDailyBudgetUsd == 25.0


def test_el_techo_configurado_manda_sobre_el_entorno(db, monkeypatch):
    from shared.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)
    service.update_settings(db, SettingsIn(llmDailyBudgetUsd=40))
    assert service.get_llm_daily_budget(db) == 40.0
    assert service.get_settings(db).llmDailyBudgetUsd == 40.0


def test_cero_es_APAGADO_A_PROPOSITO_y_no_se_confunde_con_sin_configurar(db, monkeypatch):
    """«El admin apagó el techo» y «nadie lo configuró» son estados distintos. Si un 0
    guardado se leyera como "sin configurar", el entorno lo pisaría y el admin creería
    haberlo apagado sin haberlo hecho; al revés, la plataforma queda sin techo creyendo
    que lo tiene. Los dos errores se pagan en dinero."""
    from shared.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)
    service.update_settings(db, SettingsIn(llmDailyBudgetUsd=0))
    assert service.get_llm_daily_budget(db) == 0.0, "el 0 del admin no se respetó"


def test_un_techo_guardado_ILEGIBLE_cae_al_entorno_y_nunca_a_sin_techo(db, monkeypatch):
    """«No entiendo el techo» no es «no hay techo». Tratar la primera como la segunda deja
    la plataforma sin corte justo cuando algo anda mal."""
    from shared.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)
    db.add(AppSetting(key="llm_daily_budget_usd", value="ochenta", is_secret=False))
    db.commit()
    assert service.get_llm_daily_budget(db) == 25.0


def test_un_techo_negativo_se_rechaza(db):
    with pytest.raises(ValueError):
        service.set_llm_daily_budget(db, -5)
    with pytest.raises(ValueError):
        service.update_settings(db, SettingsIn(llmDailyBudgetUsd=-1))


def test_guardar_el_techo_INVALIDA_la_memoria_del_cobrador(db, monkeypatch):
    """El techo se memoriza unos segundos en el proceso que cobra. Sin invalidarlo al
    guardar, bajarlo desde Configuración tardaría ese TTL en morder — y se baja justo
    cuando el gasto ya está corriendo."""
    from shared.llm import budget

    llamadas = []
    monkeypatch.setattr(budget, "invalidate_limit_cache", lambda: llamadas.append(1))
    service.update_settings(db, SettingsIn(llmDailyBudgetUsd=10))
    assert llamadas, "guardar el techo no invalidó la caché del cobrador"
