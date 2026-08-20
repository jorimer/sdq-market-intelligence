import re

import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from shared.config.settings import settings
from shared.narrative.lang_context import resolve_request_lang
from shared.observability import configure_logging, init_sentry
from shared.observability.health import liveness, readiness

# Logging primero (para que todo log —incluida la confirmación de Sentry— salga ya en
# el formato correcto), luego Sentry (captura errores del arranque a partir de aquí).
configure_logging()
init_sentry()

app = FastAPI(
    title="SDQ Market Intelligence",
    description="Plataforma de Inteligencia Financiera Integral",
    version="1.0.0",
    # Dependencia global: fija el idioma de la request (X-Lang) para las narrativas IA.
    dependencies=[Depends(resolve_request_lang)],
)

# CORS restrictivo (brecha 2 del DD): allowlist explícita en vez de "*". La SPA de prod
# es same-origin (se sirve desde este mismo app) así que no depende de CORS; la lista
# cubre el dev server de Vite y orígenes extra vía CORS_ORIGINS. Con credenciales
# (cookies httpOnly) los navegadores exigen origen y headers explícitos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Lang"],
)


_ID_EN_RUTA = re.compile(
    r"/(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\d+)(?=/|$)"
)


@app.middleware("http")
async def _atribuir_gasto_del_modelo(request, call_next):
    """Toda llamada al modelo hecha durante una petición queda a nombre de su ruta.

    Sin esto, el gasto que pide una persona aparece como «desconocido» y se vuelve
    indistinguible del que genera una tarea agendada — la distinción por la que existe el
    registro. Pasó: el primer informe medido en producción registró sus veinte llamadas
    sin dueño, porque la atribución estaba cableada en las operaciones y no acá.

    Se usa el path CRUDO, no la ruta con plantilla: ``request.scope["route"]`` todavía no
    existe antes de enrutar —se comprobó— y esperar a tenerla obligaría a fijar el
    contexto después de la llamada, que es tarde. Solo se normalizan los identificadores
    opacos (UUID y numéricos) para que no exploten la cardinalidad. El slug SÍ se conserva:
    saber qué encargo consume cuánto es información, no ruido.
    """
    from shared.observability.llm_ledger import attributed_to

    ruta = _ID_EN_RUTA.sub("/{id}", request.url.path)
    with attributed_to("endpoint", f"{request.method} {ruta}"[:160]):
        return await call_next(request)


@app.get("/api/v1/health")
async def health():
    """Readiness: toca DB (y Redis si está configurado). 503 si una dependencia
    configurada está caída — para que Railway no promueva/mantenga una réplica que
    arranca pero no puede servir. Es el path que Railway chequea (railway.toml)."""
    healthy, payload = readiness()
    if not healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/v1/health/live")
async def health_live():
    """Liveness: el proceso está vivo. Estático, no toca dependencias (un blip de
    DB no debe disparar reinicios)."""
    return liveness()


# --- Module routers ---
from shared.auth.router import router as auth_router
from shared.auth.admin_router import router as users_admin_router
from modules.banking_score.api.router_scoring import router as scoring_router
from modules.banking_score.api.router_data import router as data_router
from modules.banking_score.api.router_reports import router as reports_router
from modules.banking_score.api.router_model import router as model_router
from modules.banking_score.api.router_historical import router as banking_historical_router
from modules.macro_political_risk.api.router_scoring import router as mpr_scoring_router
from modules.macro_monitor.api.router import router as macro_monitor_router
from modules.law_intel.api.router import router as law_intel_router
from modules.trade_intel.api.router import router as trade_intel_router
from modules.sector_intel.api.router import router as sector_intel_router
from modules.sector_intel.events import register_subscribers as register_sector_subscribers
from modules.social_dev.api.router import router as social_dev_router
from modules.esg_climate.api.router import router as esg_climate_router
from modules.energy_intel.api.router import router as energy_intel_router
from modules.free_zones_intel.api.router import router as free_zones_intel_router
from modules.telecom_intel.api.router import router as telecom_intel_router
from modules.tourism_intel.api.router import router as tourism_intel_router
from modules.construction_intel.api.router import router as construction_intel_router
from modules.pension_intel.api.router import router as pension_intel_router
from modules.insurance_intel.api.router import router as insurance_intel_router
from modules.brand_intel.api.router import router as brand_intel_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(users_admin_router, prefix="/api/v1/admin/users", tags=["User Admin"])
app.include_router(scoring_router, prefix="/api/v1/banking-score", tags=["Banking Score"])
app.include_router(data_router, prefix="/api/v1/banking-score/data", tags=["Banking Data"])
app.include_router(reports_router, prefix="/api/v1/banking-score/reports", tags=["Banking Reports"])
app.include_router(model_router, prefix="/api/v1/banking-score/model", tags=["ML Model"])
app.include_router(banking_historical_router, prefix="/api/v1/banking-score/historical",
                   tags=["Banking Histórico"])
app.include_router(mpr_scoring_router, prefix="/api/v1/macro-political-risk", tags=["Macro-Political Risk"])
app.include_router(macro_monitor_router, prefix="/api/v1/macro-monitor", tags=["Macro Monitor"])
app.include_router(trade_intel_router, prefix="/api/v1/trade-intel", tags=["Trade Intel"])
app.include_router(law_intel_router, prefix="/api/v1/law-intel",
                   tags=["Law Intel"])
app.include_router(sector_intel_router, prefix="/api/v1/sector-intel", tags=["Sector Intel"])

app.include_router(social_dev_router, prefix="/api/v1/social-dev", tags=["Social Dev"])
app.include_router(esg_climate_router, prefix="/api/v1/esg-climate", tags=["ESG & Climate"])
app.include_router(energy_intel_router, prefix="/api/v1/energy-intel", tags=["Energy Intel"])
app.include_router(free_zones_intel_router, prefix="/api/v1/free-zones-intel",
                   tags=["Free Zones Intel"])
app.include_router(telecom_intel_router, prefix="/api/v1/telecom-intel", tags=["Telecom Intel"])
app.include_router(tourism_intel_router, prefix="/api/v1/tourism-intel", tags=["Tourism Intel"])
app.include_router(construction_intel_router, prefix="/api/v1/construction-intel",
                   tags=["Construction Intel"])
app.include_router(pension_intel_router, prefix="/api/v1/pension-intel", tags=["Pension Intel"])
app.include_router(insurance_intel_router, prefix="/api/v1/insurance-intel", tags=["Insurance Intel"])
# Brand Intel: datos PRIVADOS por cliente. Deliberadamente fuera del catálogo de productos
# sectoriales y de la Data API — el aislamiento se hace por encargo dentro del router.
app.include_router(brand_intel_router, prefix="/api/v1/brand-intel", tags=["Brand Intel"])

from shared.settings.router import router as settings_router
app.include_router(settings_router, prefix="/api/v1/settings", tags=["Settings"])

from shared.operations.router import router as operations_router
app.include_router(operations_router, prefix="/api/v1/operations", tags=["Operaciones"])

from shared.tools.router import router as tools_router
app.include_router(tools_router, prefix="/api/v1/tools", tags=["Tools"])

from app.deal_scoring_api import router as deal_scoring_router
app.include_router(deal_scoring_router, prefix="/api/v1/deal-scoring", tags=["Deal Scoring"])

from modules.deal_scoring.api.router import router as deal_registry_router
app.include_router(deal_registry_router, prefix="/api/v1/deal-scoring", tags=["Deal Scoring"])

from shared.products.router import router as products_router
app.include_router(products_router, prefix="/api/v1/products", tags=["Productos"])

from shared.source_intel.router import router as source_intel_router
app.include_router(source_intel_router, prefix="/api/v1/source-intel", tags=["Inteligencia de Fuentes"])

from shared.registry.router import router as data_registry_router
app.include_router(data_registry_router, prefix="/api/v1/registry", tags=["Data Registry"])

from shared.research.router import router as research_router
app.include_router(research_router, prefix="/api/v1/research", tags=["Motor de Research Custom"])

from shared.billing.router import router as billing_router
app.include_router(billing_router, prefix="/api/v1/billing", tags=["Billing"])

from shared.notifications.router import router as notifications_router
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["Notificaciones"])

# Watchlist de alertas: qué vigila cada cliente (fase A de
# docs/SPEC_ALERTA_ACCIONABLE.md). Transversal a los 16 ejes, por eso vive en shared/.
from shared.alerts.router import router as alerts_router
app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["Alertas"])

# Data API — contrato PÚBLICO máquina-a-máquina, namespace propio y versionado. Va
# separado de /api/v1 a propósito: /api/v1 sirve a la SPA y cambia con ella; este
# contrato lo consumen terceros y no puede romperse por un refactor del frontend.
from shared.data_api.router import router as data_api_router
app.include_router(data_api_router, prefix="/api/data/v1", tags=["Data API"])

from shared.data_api.admin_router import router as data_api_admin_router
app.include_router(data_api_admin_router, prefix="/api/v1/admin/data-api", tags=["Data API · Admin"])

# Event subscriptions across axes (string contract via event_bus)
from modules.banking_score.events import register_subscribers as register_banking_subscribers
from shared.products.events import subscribe_product_events
from shared.billing.events import subscribe_billing_events

register_sector_subscribers()  # sector_intel ← macro/irmp/trade .updated (SGPS acceleration)
register_banking_subscribers()  # banking_score ← irmp.updated (outlook overlay)
subscribe_product_events()  # monitor de productos ← *.updated (recálculo de readiness)
subscribe_billing_events()  # alerta de tarifa ← tariff.published (notifica a suscriptos)

from shared.narrative.degradation_events import subscribe_narrative_degradation_events
subscribe_narrative_degradation_events()  # ops ← narrative.degraded (alerta de PDF hueco bloqueado)

from shared.data_api.webhooks import subscribe_webhook_events
subscribe_webhook_events()  # webhooks de clientes ← *.updated (aviso de dato nuevo)

# Operation Console: each module registers its operations at import time into the
# shared registry (shared.operations). Import the register modules so the console
# sees every operation, then (web-only, env-gated) start the in-app scheduler.
import modules.banking_score.operations  # noqa: F401 — registers banking ops
import modules.macro_monitor.operations  # noqa: F401 — registers fiscal-sync
import modules.macro_political_risk.operations  # noqa: F401 — registers wgi-sync
import modules.sector_intel.operations  # noqa: F401 — registers bcrd-sectores-sync
import modules.social_dev.operations  # noqa: F401 — registers one-social-sync
import modules.trade_intel.operations  # noqa: F401 — registers dga-trade-sync
import modules.esg_climate.operations  # noqa: F401 — registers esg-sync
import modules.energy_intel.operations  # noqa: F401 — registers sie-energy-sync
import modules.free_zones_intel.operations  # noqa: F401 — registers cnzfe-free-zones-sync
import modules.telecom_intel.operations  # noqa: F401 — registers indotel-telecom-sync
import modules.tourism_intel.operations  # noqa: F401 — registers one-tourism-sync
import modules.construction_intel.operations  # noqa: F401 — registers mivhed-construction-sync
import modules.pension_intel.operations  # noqa: F401 — registers sipen-sync
import modules.insurance_intel.operations  # noqa: F401 — registers insurance-sync
import app.market_brief as _market_brief_ops  # noqa: F401 — registers market-brief (app-level)
import shared.billing.operations  # noqa: F401 — registers fiscal-sequence-watch (NCF/e-NCF)
import shared.products.operations  # noqa: F401 — registers products-readiness-recompute
import shared.source_intel.operations  # noqa: F401 — registers source-research-agent (Capa 3)
import shared.reference.operations  # noqa: F401 — registers dgii-contribuyentes-sync
import shared.operations.freshness  # noqa: F401 — registers data-freshness-audit (alerta dato viejo)
import shared.alerts.motor  # noqa: F401 — registers alerts-sweep (barrido de alertas)
import shared.alerts.digest  # noqa: F401 — registers alerts-digest (resúmenes por correo)
import modules.banking_score.alerts_producer  # noqa: F401 — banca aporta señales al barrido
import modules.macro_monitor.comunicados.freshness  # noqa: F401 — registra frescura de decisiones TPM

# Product catalog: each sector registers its SectorProduct into shared.products at
# import time (anti-Frankenstein: shared/products never imports a sector).
import modules.banking_score.products  # noqa: F401 — registers banking SectorProduct
import modules.trade_intel.products  # noqa: F401 — registers trade SectorProduct
import modules.esg_climate.products  # noqa: F401 — registers esg SectorProduct
import modules.sector_intel.products  # noqa: F401 — registers agribusiness (slot transversal)
import modules.sector_intel.structure_product  # noqa: F401 — registers economic_structure (agregado)
import modules.free_zones_intel.products  # noqa: F401 — registers free_zones (dedicado, IZF/CNZFE)
import modules.tourism_intel.products  # noqa: F401 — registers tourism (dedicado, ITT/ONE)
import modules.construction_intel.products  # noqa: F401 — registers construction (dedicado, ICC/MIVHED+BCRD)
import modules.energy_intel.products  # noqa: F401 — registers energy SectorProduct
import modules.telecom_intel.products  # noqa: F401 — registers telecom SectorProduct
import modules.pension_intel.products  # noqa: F401 — registers pension SectorProduct
import modules.insurance_intel.products  # noqa: F401 — registers insurance SectorProduct
import modules.social_dev.products  # noqa: F401 — registers social_dev (panel SUB-NACIONAL)
import modules.law_intel.products  # noqa: F401 — registers law (sujeto = instrumento normativo)
# Macro abarca 2 módulos → su producto se ensambla a nivel app vía getters públicos.
# (forma `from app import` para NO rebindear el nombre `app` = la instancia FastAPI.)
from app import products_macro as _products_macro  # noqa: F401 — registers macro SectorProduct
from app import products_monetary_policy as _products_mp  # noqa: F401 — registers monetary_policy SectorProduct

import os as _os
if _os.getenv("SDQ_SCHEDULER") == "1":
    from shared.database.session import SessionLocal as _SessionLocal
    from shared.operations import (
        clear_orphaned_runs,
        normalize_ondemand_schedules,
        seed_default_schedules,
        start_scheduler,
    )
    # Limpia ops con is_running huérfano (un deploy anterior cortó una corrida larga a la
    # mitad): sin esto, el flag stale bloquea el reintento 30 min. Debe correr ANTES de
    # sembrar/arrancar el scheduler, que podría re-disparar esas ops.
    _boot_db = _SessionLocal()
    try:
        clear_orphaned_runs(_boot_db)
    finally:
        _boot_db.close()
    # Activa por defecto las agendas que falten (todas las syncs recurrentes corren
    # solas tras el deploy; idempotente, respeta cambios manuales), APAGA cualquier agenda
    # bajo-demanda encendida por error (backfills/backtests/purgas no van en ciclo) y arranca
    # el tick.
    seed_default_schedules()
    normalize_ondemand_schedules()
    start_scheduler()

# Serve frontend in production.
#
# Cache strategy for the SPA:
#   - index.html must NEVER be cached: it references hash-named asset files, so a
#     stale index.html points at old bundles and the user sees an outdated UI.
#     We force revalidation on every load (no-cache).
#   - /assets/* are content-hashed by Vite (e.g. index-BT2GSx-5.js); the URL
#     changes whenever the content changes, so they're safe to cache forever.
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # SPA fallback: the frontend uses BrowserRouter, so client-side routes
            # (e.g. /banking-score) have no file on disk and StaticFiles raises
            # 404. Serve index.html instead so the router can take over. Real
            # missing assets keep their 404 (their path starts with "assets/").
            if exc.status_code == 404 and not path.startswith("assets/"):
                response = await super().get_response("index.html", scope)
            else:
                raise
        # Key off the resolved content type: with html=True (and the fallback
        # above) Starlette rewrites the request path to index.html, so the request
        # path alone is unreliable for telling HTML from a hashed asset.
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            # index.html references hash-named assets; a stale copy points at old
            # bundles, so it must always be revalidated.
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif path.startswith("assets/"):
            # Content-hashed by Vite — the URL changes on every build, so cache hard.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if os.path.exists("frontend/dist"):
    app.mount("/", SPAStaticFiles(directory="frontend/dist", html=True), name="frontend")
