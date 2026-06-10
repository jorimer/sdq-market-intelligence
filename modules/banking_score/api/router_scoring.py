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
from modules.banking_score.scoring.engine import (
    calculate_deterministic_score,
    run_scoring,
    simulate_from_scores,
)
from modules.banking_score.scoring.batch import detect_rating_action, score_period
from modules.banking_score.scoring.indicator_detail import ai_context, build_indicator_detail
from modules.banking_score.scoring.entity_insight import ai_context_entity, build_entity_insight
from modules.banking_score.scoring.rating_scale import get_tier_color, map_rating_tier
from modules.banking_score.scoring.weights import (
    WEIGHT_PROFILES,
    get_sub_component_weights,
)

logger = logging.getLogger("sdq.api.scoring")

router = APIRouter()


@router.get(
    "/weights",
    summary="Perfiles de peso por tipo de entidad",
    description="Devuelve el perfil de pesos de sub-componentes (base o por entity_type).",
)
async def get_weights(
    entity_type: Optional[str] = Query(None, description="Tipo de entidad SIB"),
    current_user: User = Depends(get_current_user),
):
    return {
        "entity_type": entity_type,
        "weights": get_sub_component_weights(entity_type),
        "available_profiles": sorted(WEIGHT_PROFILES.keys()),
    }


@router.post(
    "/simulate-scenario",
    summary="Simulación what-if por sub-componentes",
    description="Recalcula score y rating desde sub-componentes modificados (0-100). Determinista, sin persistir.",
)
async def simulate_scenario(
    body: Dict[str, Any] = Body(
        ...,
        examples=[{"sub_components": {"solidez": 80, "calidad": 70, "eficiencia": 60, "liquidez": 65, "diversificacion": 55}, "entity_type": "banca_multiple"}],
    ),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    subs = body.get("sub_components")
    if not isinstance(subs, dict) or not subs:
        raise HTTPException(status_code=400, detail="Se requiere 'sub_components'.")
    weights = get_sub_component_weights(body.get("entity_type"))
    overall = calculate_deterministic_score(subs, weights)
    tier = map_rating_tier(overall)
    return {
        "sub_components": subs,
        "overall_score": overall,
        "rating_tier": tier,
        "tier_color": get_tier_color(tier),
    }


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
        result = run_scoring(data, entity_type=bank.bank_type.value if bank.bank_type else None)
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
    rating_action_info = detect_rating_action(db, bank_id, pe, result, current_user.id)

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

    if not db.query(BankingData).filter_by(period_end=pe).first():
        raise HTTPException(status_code=404, detail=f"No hay datos bancarios para el período {period_end}")

    summary = score_period(db, pe, created_by=current_user.id)
    return {"success": True, **summary}


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


# ─── Indicator drill-down (detail + trend + peers + AI insight) ──


@router.get(
    "/{bank_id}/indicator/{indicator_key}",
    summary="Drill-down de un indicador",
    description="Detalle de un indicador para un banco: valor/score/interpretación, "
                "tendencia histórica, posición vs pares (sector y tipo de entidad), e "
                "insight de IA (Claude, SCQA). El insight se cachea ~1h.",
)
async def get_indicator_detail(
    bank_id: str,
    indicator_key: str,
    with_ai: bool = Query(True, description="Incluir insight de IA (Claude)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Banco {bank_id} no encontrado")

    detail = build_indicator_detail(db, bank, indicator_key)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"Indicador '{indicator_key}' no reconocido o el banco no tiene calificaciones.",
        )

    detail["ai_insight"] = None
    if with_ai and detail["latest"]["available"]:
        try:
            from shared.narrative.claude_engine import narrative_engine
            res = await narrative_engine.generate(
                ai_context(detail), template="indicator_insight", mode="detailed",
            )
            detail["ai_insight"] = {
                "text": res.text,
                "model_used": res.model_used,
                "from_cache": res.from_cache,
            }
        except Exception as e:  # noqa: BLE001 — AI is best-effort; never break the drill-down
            logger.warning("AI insight no disponible para %s/%s: %s", bank_id, indicator_key, e)

    return detail


# ─── Entity drill-down (overall rating + sub-component drivers + AI) ──


@router.get(
    "/{bank_id}/insight",
    summary="Drill-down de entidad",
    description="Rating global + sub-componentes (impulsores/lastres) + posición vs pares + "
                "tendencia del score, e insight de IA ('fundamento del rating', cacheado ~1h).",
)
async def get_entity_insight(
    bank_id: str,
    with_ai: bool = Query(True, description="Incluir insight de IA (Claude)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank = db.query(Bank).filter_by(id=bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Banco {bank_id} no encontrado")

    detail = build_entity_insight(db, bank)
    if detail is None:
        raise HTTPException(status_code=404, detail="El banco no tiene calificaciones.")

    detail["ai_insight"] = None
    if with_ai:
        try:
            from shared.narrative.claude_engine import narrative_engine
            res = await narrative_engine.generate(
                ai_context_entity(detail), template="entity_rating", mode="detailed",
            )
            detail["ai_insight"] = {
                "text": res.text,
                "model_used": res.model_used,
                "from_cache": res.from_cache,
            }
        except Exception as e:  # noqa: BLE001 — AI is best-effort; never break the drill-down
            logger.warning("AI insight de entidad no disponible para %s: %s", bank_id, e)

    return detail


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
    entity_type: Optional[str] = Query(None, description="Filtrar por tipo de entidad SIB"),
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

    if entity_type:
        results = [
            (rr, bank) for rr, bank in results
            if bank.bank_type and bank.bank_type.value == entity_type
        ]

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


# ─── Banks (catálogo) ────────────────────────────────────────────

@router.get(
    "/banks",
    summary="Catálogo de entidades",
    description="Lista de entidades activas (id, nombre, tipo) para selectores.",
)
async def list_banks(
    entity_type: Optional[str] = Query(None, description="Filtrar por tipo de entidad"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Bank).filter(Bank.is_active.is_(True))
    banks = q.order_by(Bank.name).all()
    items = [
        {
            "id": b.id,
            "name": b.name,
            "bank_type": b.bank_type.value if b.bank_type else None,
        }
        for b in banks
        if not entity_type or (b.bank_type and b.bank_type.value == entity_type)
    ]
    return {"banks": items, "count": len(items)}


# ─── Periods ─────────────────────────────────────────────────────

@router.get(
    "/periods",
    summary="Períodos disponibles",
    description="Lista de períodos (period_end) con datos bancarios, más reciente primero.",
)
async def get_periods(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(BankingData.period_end)
        .distinct()
        .order_by(BankingData.period_end.desc())
        .all()
    )
    periods = [str(r[0]) for r in rows]
    return {"periods": periods, "count": len(periods)}


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
