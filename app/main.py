import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
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

app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(scoring_router, prefix="/api/v1/banking-score", tags=["Banking Score"])
app.include_router(data_router, prefix="/api/v1/banking-score/data", tags=["Banking Data"])
app.include_router(reports_router, prefix="/api/v1/banking-score/reports", tags=["Banking Reports"])
app.include_router(model_router, prefix="/api/v1/banking-score/model", tags=["ML Model"])

# Serve frontend in production
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
