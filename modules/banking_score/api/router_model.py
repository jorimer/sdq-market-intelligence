"""Banking Score — ML Model endpoints.

prefix: /api/v1/banking-score/model
Extracted from monolith router_banking_scoring.py.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.banking_score.models.models import BankingData, RatingResult
from modules.banking_score.ml.xgboost_model import xgboost_model
from modules.banking_score.ml.features import extract_feature_vector
from modules.banking_score.scoring.engine import (
    calculate_all_indicators,
    calculate_sub_components,
    calculate_deterministic_score,
)
from modules.banking_score.scoring.rating_scale import map_rating_tier

logger = logging.getLogger("sdq.api.model")

router = APIRouter()


# ─── Model Status ────────────────────────────────────────────────

@router.get(
    "/status",
    summary="Estado del modelo ML",
    description="Retorna el estado del modelo XGBoost (disponible, versión, métricas).",
)
async def get_model_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_records = db.query(func.count(BankingData.id)).scalar()
    total_ratings = db.query(func.count(RatingResult.id)).scalar()
    model_status = xgboost_model.get_status()

    return {
        "ml_available": model_status["model_available"],
        "model_type": "xgboost" if model_status["model_available"] else "deterministic",
        "model_version": model_status.get("version", "1.0"),
        "model_metrics": model_status.get("metrics"),
        "training_records": total_records,
        "total_ratings": total_ratings,
        "min_records_for_training": 30,
        "can_train": total_records >= 30,
    }


# ─── Train Model ─────────────────────────────────────────────────

@router.post(
    "/train",
    summary="Entrenar XGBoost",
    description="Entrena o re-entrena el modelo XGBoost. Requiere al menos 30 registros.",
)
async def train_model(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_records = db.query(func.count(BankingData.id)).scalar()

    if total_records < 30:
        raise HTTPException(
            status_code=400,
            detail=f"Se necesitan al menos 30 registros para entrenar. "
                   f"Actualmente hay {total_records}.",
        )

    # Gather all banking data records and compute feature vectors + tiers
    records = db.query(BankingData).all()
    features = []
    tiers = []

    for record in records:
        try:
            indicators = calculate_all_indicators(record)
            sub_scores = calculate_sub_components(indicators)
            overall = calculate_deterministic_score(sub_scores)
            tier = map_rating_tier(overall)

            flat_scores = {k: v["score"] for k, v in indicators.items()}
            vec = extract_feature_vector(flat_scores)
            features.append(vec)
            tiers.append(tier)
        except Exception as e:
            logger.warning("Skipping record %s: %s", record.id, e)

    if len(features) < 30:
        raise HTTPException(
            status_code=400,
            detail=f"Solo {len(features)} registros válidos de {total_records}. "
                   f"Se necesitan al menos 30.",
        )

    try:
        metrics = xgboost_model.train(features, tiers)
    except Exception as e:
        logger.error("Training failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Error en entrenamiento: {e}")

    return {
        "success": True,
        "message": "Modelo XGBoost entrenado exitosamente.",
        "records_used": len(features),
        "metrics": metrics,
        "version": xgboost_model.version,
    }
