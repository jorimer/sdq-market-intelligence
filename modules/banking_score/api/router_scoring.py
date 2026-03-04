"""Banking Score — Scoring endpoints.

prefix: /api/v1/banking-score
Extracted from monolith router_banking_scoring.py.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.banking_score.models.models import (
    Bank,
    BankingData,
    RatingResult,
    RatingAction,
    ActionType,
    ModelType,
    Outlook,
)
from modules.banking_score.scoring.engine import run_scoring, simulate_from_scores

logger = logging.getLogger("sdq.api.scoring")

router = APIRouter()


# ─── Run scoring for one bank ────────────────────────────────────

@router.post(
    "/{bank_id}/run",
    summary="Ejecutar scoring para un banco",
    description="Calcula 19 indicadores, sub-componentes y rating general para un banco/período.",
)
async def run_bank_scoring(
    bank_id: str,
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Banco {bank_id} no encontrado")

    try:
        pe = date.fromisoformat(period_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    data = db.query(BankingData).filter_by(bank_id=bank_id, period_end=pe).first()
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No hay datos bancarios para {bank.name} en período {period_end}",
        )

    try:
        result = run_scoring(data)
    except Exception as e:
        logger.error(f"Error de scoring para {bank_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error ejecutando scoring: {e}")

    # Persist RatingResult
    existing = db.query(RatingResult).filter_by(
        bank_id=bank_id, period_end=pe, model_type=ModelType.deterministic,
    ).first()

    if existing:
        existing.overall_score = result["overall_score"]
        existing.rating_tier = result["rating_tier"]
        existing.solidez_score = result["sub_components"]["solidez"]
        existing.calidad_score = result["sub_components"]["calidad"]
        existing.eficiencia_score = result["sub_components"]["eficiencia"]
        existing.liquidez_score = result["sub_components"]["liquidez"]
        existing.diversificacion_score = result["sub_components"]["diversificacion"]
        existing.indicator_details = result["indicators"]
        existing.model_version = result["model_version"]
    else:
        rr = RatingResult(
            bank_id=bank_id,
            period_end=pe,
            overall_score=result["overall_score"],
            rating_tier=result["rating_tier"],
            solidez_score=result["sub_components"]["solidez"],
            calidad_score=result["sub_components"]["calidad"],
            eficiencia_score=result["sub_components"]["eficiencia"],
            liquidez_score=result["sub_components"]["liquidez"],
            diversificacion_score=result["sub_components"]["diversificacion"],
            indicator_details=result["indicators"],
            model_type=ModelType.deterministic,
            model_version=result["model_version"],
            created_by=current_user.id,
        )
        db.add(rr)

    # ── Detect rating action (compare with previous period) ──
    rating_action_info = _detect_rating_action(db, bank_id, pe, result, current_user.id)

    db.commit()
    logger.info(f"Scoring completado: {bank.name} | {period_end} → {result['rating_tier']}")

    return {
        "bank_id": bank_id,
        "bank_name": bank.name,
        "period_end": period_end,
        **result,
        "rating_action": rating_action_info,
    }


# ─── Run scoring for all banks ───────────────────────────────────

@router.post(
    "/run-all",
    summary="Scoring masivo para todos los bancos",
    description="Ejecuta scoring para todos los bancos que tengan datos en el período indicado.",
)
async def run_scoring_all(
    period_end: str = Query(..., description="Fecha fin del período (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pe = date.fromisoformat(period_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    records = db.query(BankingData).filter_by(period_end=pe).all()
    if not records:
        raise HTTPException(status_code=404, detail=f"No hay datos bancarios para el período {period_end}")

    results: List[Dict] = []
    errors: List[Dict] = []

    for record in records:
        try:
            scoring_result = run_scoring(record)
            bank = db.query(Bank).filter_by(id=record.bank_id).first()

            # Persist
            existing = db.query(RatingResult).filter_by(
                bank_id=record.bank_id, period_end=pe, model_type=ModelType.deterministic,
            ).first()
            if existing:
                existing.overall_score = scoring_result["overall_score"]
                existing.rating_tier = scoring_result["rating_tier"]
                existing.solidez_score = scoring_result["sub_components"]["solidez"]
                existing.calidad_score = scoring_result["sub_components"]["calidad"]
                existing.eficiencia_score = scoring_result["sub_components"]["eficiencia"]
                existing.liquidez_score = scoring_result["sub_components"]["liquidez"]
                existing.diversificacion_score = scoring_result["sub_components"]["diversificacion"]
                existing.indicator_details = scoring_result["indicators"]
            else:
                rr = RatingResult(
                    bank_id=record.bank_id, period_end=pe,
                    overall_score=scoring_result["overall_score"],
                    rating_tier=scoring_result["rating_tier"],
                    solidez_score=scoring_result["sub_components"]["solidez"],
                    calidad_score=scoring_result["sub_components"]["calidad"],
                    eficiencia_score=scoring_result["sub_components"]["eficiencia"],
                    liquidez_score=scoring_result["sub_components"]["liquidez"],
                    diversificacion_score=scoring_result["sub_components"]["diversificacion"],
                    indicator_details=scoring_result["indicators"],
                    model_type=ModelType.deterministic,
                    model_version=scoring_result["model_version"],
                    created_by=current_user.id,
                )
                db.add(rr)

            action_info = _detect_rating_action(db, record.bank_id, pe, scoring_result, current_user.id)

            results.append({
                "bank_id": record.bank_id,
                "bank_name": bank.name if bank else "Desconocido",
                "overall_score": scoring_result["overall_score"],
                "rating_tier": scoring_result["rating_tier"],
                "rating_action": action_info,
            })
        except Exception as e:
            errors.append({"bank_id": record.bank_id, "error": str(e)})

    db.commit()

    summary = {"upgrades": 0, "downgrades": 0, "confirmaciones": 0, "observaciones": 0}
    for r in results:
        act = r.get("rating_action")
        if act:
            key = act.get("action_type", "")
            if key == "upgrade":
                summary["upgrades"] += 1
            elif key == "downgrade":
                summary["downgrades"] += 1
            elif key == "confirmacion":
                summary["confirmaciones"] += 1
            elif key == "observacion":
                summary["observaciones"] += 1

    return {
        "success": True,
        "period_end": period_end,
        "scored": len(results),
        "errors": errors,
        "results": results,
        "rating_actions_summary": summary,
    }


# ─── Get Latest Rating ──────────────────────────────────────────

@router.get(
    "/{bank_id}/latest",
    summary="Obtener último rating",
    description="Retorna el rating más reciente calculado para el banco.",
)
async def get_latest_rating(
    bank_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = (
        db.query(RatingResult)
        .filter_by(bank_id=bank_id)
        .order_by(RatingResult.period_end.desc())
        .first()
    )
    if not result:
        return {"has_rating": False, "bank_id": bank_id}

    bank = db.query(Bank).filter_by(id=bank_id).first()
    return {
        "has_rating": True,
        "bank_id": bank_id,
        "bank_name": bank.name if bank else None,
        "period_end": str(result.period_end),
        "overall_score": float(result.overall_score),
        "rating_tier": result.rating_tier,
        "solidez_score": float(result.solidez_score or 0),
        "calidad_score": float(result.calidad_score or 0),
        "eficiencia_score": float(result.eficiencia_score or 0),
        "liquidez_score": float(result.liquidez_score or 0),
        "diversificacion_score": float(result.diversificacion_score or 0),
        "indicator_details": result.indicator_details,
        "model_type": result.model_type.value if result.model_type else "deterministic",
        "model_version": result.model_version,
    }


# ─── Rating History ──────────────────────────────────────────────

@router.get(
    "/{bank_id}/history",
    summary="Historial de ratings",
    description="Historial de ratings calculados para un banco.",
)
async def get_rating_history(
    bank_id: str,
    limit: int = Query(20, ge=1, le=100, description="Cantidad máxima de registros"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(RatingResult)
        .filter_by(bank_id=bank_id)
        .order_by(RatingResult.period_end.desc())
        .limit(limit)
        .all()
    )
    history = [
        {
            "period_end": str(r.period_end),
            "overall_score": float(r.overall_score),
            "rating_tier": r.rating_tier,
            "solidez_score": float(r.solidez_score or 0),
            "calidad_score": float(r.calidad_score or 0),
            "eficiencia_score": float(r.eficiencia_score or 0),
            "liquidez_score": float(r.liquidez_score or 0),
            "diversificacion_score": float(r.diversificacion_score or 0),
            "model_type": r.model_type.value if r.model_type else "deterministic",
        }
        for r in records
    ]
    return {"bank_id": bank_id, "history": history, "count": len(history)}


# ─── Rankings ────────────────────────────────────────────────────

@router.get(
    "/rankings",
    summary="Rankings de bancos",
    description="Ranking de bancos ordenados por score SDQ.",
)
async def get_rankings(
    period_end: str = Query(None, description="Filtro por período (YYYY-MM-DD). Si se omite, muestra el último rating de cada banco."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if period_end:
        try:
            pe = date.fromisoformat(period_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")
        results = (
            db.query(RatingResult, Bank)
            .join(Bank, Bank.id == RatingResult.bank_id)
            .filter(RatingResult.period_end == pe)
            .order_by(RatingResult.overall_score.desc())
            .all()
        )
    else:
        from sqlalchemy import and_
        subq = (
            db.query(
                RatingResult.bank_id,
                func.max(RatingResult.period_end).label("max_pe"),
            )
            .group_by(RatingResult.bank_id)
            .subquery()
        )
        results = (
            db.query(RatingResult, Bank)
            .join(Bank, Bank.id == RatingResult.bank_id)
            .join(subq, and_(
                RatingResult.bank_id == subq.c.bank_id,
                RatingResult.period_end == subq.c.max_pe,
            ))
            .order_by(RatingResult.overall_score.desc())
            .all()
        )

    rankings = [
        {
            "rank": i + 1,
            "bank_id": rr.bank_id,
            "bank_name": bank.name,
            "bank_type": bank.bank_type.value if bank.bank_type else None,
            "period_end": str(rr.period_end),
            "overall_score": float(rr.overall_score),
            "rating_tier": rr.rating_tier,
        }
        for i, (rr, bank) in enumerate(results)
    ]
    return {"rankings": rankings, "count": len(rankings), "period_end": period_end or "latest"}


# ─── Stats ───────────────────────────────────────────────────────

@router.get(
    "/stats",
    summary="Estadísticas agregadas del sector",
    description="Resumen de datos bancarios cargados y ratings calculados.",
)
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_records = db.query(func.count(BankingData.id)).scalar()
    total_entities = db.query(func.count(func.distinct(BankingData.bank_id))).scalar()
    total_ratings = db.query(func.count(RatingResult.id)).scalar()

    date_range = db.query(
        func.min(BankingData.period_end),
        func.max(BankingData.period_end),
    ).first()

    entity_counts = (
        db.query(Bank.name, func.count(BankingData.id))
        .join(Bank, Bank.id == BankingData.bank_id)
        .group_by(Bank.name)
        .order_by(func.count(BankingData.id).desc())
        .all()
    )

    return {
        "total_records": total_records,
        "total_entities": total_entities,
        "total_ratings": total_ratings,
        "period_start": str(date_range[0]) if date_range[0] else None,
        "period_end": str(date_range[1]) if date_range[1] else None,
        "entities": [{"name": name, "records": count} for name, count in entity_counts],
    }


# ─── Simulate ────────────────────────────────────────────────────

@router.post(
    "/{bank_id}/simulate",
    summary="Simulación what-if",
    description="Recalcula rating desde scores de indicadores modificados (iSRM).",
)
async def simulate(
    bank_id: str,
    body: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
):
    if not body or "modified_scores" not in body:
        raise HTTPException(status_code=400, detail="Se requiere 'modified_scores' en el body")
    try:
        result = simulate_from_scores(body["modified_scores"])
        return {"bank_id": bank_id, **result}
    except Exception as e:
        logger.error(f"Error en simulación para {bank_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error en simulación: {e}")


# ─── Helpers ─────────────────────────────────────────────────────

def _detect_rating_action(
    db: Session,
    bank_id: str,
    period_end: date,
    scoring_result: Dict[str, Any],
    user_id: str,
) -> Optional[Dict]:
    """Compare current scoring with previous period and create a RatingAction if applicable."""
    previous = (
        db.query(RatingResult)
        .filter(RatingResult.bank_id == bank_id, RatingResult.period_end < period_end)
        .order_by(RatingResult.period_end.desc())
        .first()
    )
    if not previous:
        return None

    score_delta = round(float(scoring_result["overall_score"]) - float(previous.overall_score), 2)
    prev_tier = previous.rating_tier
    new_tier = scoring_result["rating_tier"]

    if new_tier != prev_tier:
        action_type = ActionType.upgrade if scoring_result["overall_score"] > float(previous.overall_score) else ActionType.downgrade
    elif abs(score_delta) >= 2.0:
        action_type = ActionType.observacion
    else:
        action_type = ActionType.confirmacion

    outlook = Outlook.positiva if score_delta > 3 else (Outlook.negativa if score_delta < -3 else Outlook.estable)

    action = RatingAction(
        bank_id=bank_id,
        period_end=period_end,
        action_type=action_type,
        previous_period_end=previous.period_end,
        previous_score=previous.overall_score,
        previous_tier=prev_tier,
        new_score=scoring_result["overall_score"],
        new_tier=new_tier,
        score_delta=score_delta,
        outlook=outlook,
        previous_sub_components={
            "solidez": float(previous.solidez_score or 0),
            "calidad": float(previous.calidad_score or 0),
            "eficiencia": float(previous.eficiencia_score or 0),
            "liquidez": float(previous.liquidez_score or 0),
            "diversificacion": float(previous.diversificacion_score or 0),
        },
        new_sub_components=scoring_result["sub_components"],
        created_by=user_id,
    )
    db.add(action)

    return {
        "action_type": action_type.value,
        "previous_tier": prev_tier,
        "new_tier": new_tier,
        "score_delta": score_delta,
        "outlook": outlook.value,
    }
