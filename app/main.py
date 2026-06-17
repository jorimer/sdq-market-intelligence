import logging
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

# Log to stdout so platform log collectors (Railway) don't flag INFO as errors.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

app = FastAPI(
    title="SDQ Market Intelligence",
    description="Plataforma de Inteligencia Financiera Integral",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "platform": "SDQ Market Intelligence", "version": "1.0.0"}


# --- Module routers ---
from shared.auth.router import router as auth_router
from modules.banking_score.api.router_scoring import router as scoring_router
from modules.banking_score.api.router_data import router as data_router
from modules.banking_score.api.router_reports import router as reports_router
from modules.banking_score.api.router_model import router as model_router
from modules.macro_political_risk.api.router_scoring import router as mpr_scoring_router
from modules.macro_monitor.api.router import router as macro_monitor_router
from modules.trade_intel.api.router import router as trade_intel_router
from modules.sector_intel.api.router import router as sector_intel_router
from modules.sector_intel.events import register_subscribers as register_sector_subscribers
from modules.social_dev.api.router import router as social_dev_router
from modules.esg_climate.api.router import router as esg_climate_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(scoring_router, prefix="/api/v1/banking-score", tags=["Banking Score"])
app.include_router(data_router, prefix="/api/v1/banking-score/data", tags=["Banking Data"])
app.include_router(reports_router, prefix="/api/v1/banking-score/reports", tags=["Banking Reports"])
app.include_router(model_router, prefix="/api/v1/banking-score/model", tags=["ML Model"])
app.include_router(mpr_scoring_router, prefix="/api/v1/macro-political-risk", tags=["Macro-Political Risk"])
app.include_router(macro_monitor_router, prefix="/api/v1/macro-monitor", tags=["Macro Monitor"])
app.include_router(trade_intel_router, prefix="/api/v1/trade-intel", tags=["Trade Intel"])
app.include_router(sector_intel_router, prefix="/api/v1/sector-intel", tags=["Sector Intel"])

app.include_router(social_dev_router, prefix="/api/v1/social-dev", tags=["Social Dev"])
app.include_router(esg_climate_router, prefix="/api/v1/esg-climate", tags=["ESG & Climate"])

from shared.settings.router import router as settings_router
app.include_router(settings_router, prefix="/api/v1/settings", tags=["Settings"])

from shared.operations.router import router as operations_router
app.include_router(operations_router, prefix="/api/v1/operations", tags=["Operaciones"])

# Event subscriptions across axes (string contract via event_bus)
from modules.banking_score.events import register_subscribers as register_banking_subscribers

register_sector_subscribers()  # sector_intel ← macro/irmp/trade .updated (SGPS acceleration)
register_banking_subscribers()  # banking_score ← irmp.updated (outlook overlay)

# Operation Console: each module registers its operations at import time into the
# shared registry (shared.operations). Import the register modules so the console
# sees every operation, then (web-only, env-gated) start the in-app scheduler.
import modules.banking_score.operations  # noqa: F401 — registers banking ops
import modules.macro_political_risk.operations  # noqa: F401 — registers wgi-sync
import modules.sector_intel.operations  # noqa: F401 — registers bcrd-sectores-sync
import modules.social_dev.operations  # noqa: F401 — registers one-social-sync

import os as _os
if _os.getenv("SDQ_SCHEDULER") == "1":
    from shared.operations import start_scheduler
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
