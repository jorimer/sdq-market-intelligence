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
    Fideicomiso,
    FideicomisoData,
    FideicomisoHealthScore,
)
from modules.banking_score.scoring.engine import (
    calculate_deterministic_score,
    run_scoring,
    simulate_from_scores,
)
from modules.banking_score.scoring.batch import detect_rating_action, score_period
from modules.banking_score.ml.xgboost_model import xgboost_model
from modules.banking_score.scoring.indicator_detail import ai_context, build_indicator_detail
from modules.banking_score.scoring.entity_insight import ai_context_entity, build_entity_insight
from shared.publications.service import publication_prompt_context
from modules.banking_score.scoring.rating_scale import get_tier_color, map_rating_tier
from modules.banking_score.scoring.weights import (
    WEIGHT_PROFILES,
    get_sub_component_weights,
)

logger = logging.getLogger("sdq.api.scoring")

router = APIRouter()


async def _ai_insight(context: Dict[str, Any], template: str) -> Optional[Dict[str, Any]]:
    """Generate a Claude narrative from *context* using *template*; best-effort
    (returns None on any failure so the endpoint never breaks)."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template=template, mode="detailed")
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001
        logger.warning("AI insight (%s) no disponible: %s", template, e)
        return None


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
    model: str = Query("deterministic", description="Modelo de scoring: 'deterministic' o 'ml' (XGBoost)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if model not in ("deterministic", "ml"):
        raise HTTPException(status_code=400, detail="model debe ser 'deterministic' o 'ml'")

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
        # Indicators & sub-components are always computed deterministically — they
        # are also the ML model's feature inputs.
        result = run_scoring(data, entity_type=bank.bank_type.value if bank.bank_type else None)
    except Exception as e:
        logger.error(f"Error de scoring para {bank_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error ejecutando scoring: {e}")

    model_type = ModelType.deterministic
    if model == "ml":
        if not xgboost_model.ensure_loaded(db):
            raise HTTPException(
                status_code=400,
                detail="El modelo ML no está entrenado. Entrénalo en la sección Modelo.",
            )
        try:
            flat_scores = {k: v.get("score", 0.0) for k, v in (result.get("indicators") or {}).items()}
            ml_score, ml_tier, ml_probs = xgboost_model.predict(flat_scores)
        except Exception as e:
            logger.error(f"Error en predicción ML para {bank_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Error en predicción ML: {e}")
        # ML overrides the overall score/tier; sub-components & indicators (the
        # deterministic features) are kept for explainability.
        result["overall_score"] = ml_score
        result["rating_tier"] = ml_tier
        result["tier_color"] = get_tier_color(ml_tier)
        result["tier_probabilities"] = ml_probs
        result["model_version"] = xgboost_model.version or result.get("model_version")
        model_type = ModelType.ml
    result["model"] = model

    # Persist RatingResult (deterministic and ml coexist via the unique constraint)
    existing = db.query(RatingResult).filter_by(
        bank_id=bank_id, period_end=pe, model_type=model_type,
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
            model_type=model_type,
            model_version=result["model_version"],
            created_by=current_user.id,
        )
        db.add(rr)

    # ── Detect rating action (compare with previous period) ──
    # Rating actions track the canonical (deterministic) series only.
    rating_action_info = None
    if model_type == ModelType.deterministic:
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


@router.get(
    "/{bank_id}/periods",
    summary="Períodos con datos de una entidad",
    description="Períodos (period_end ISO, descendente) para los que la entidad tiene "
                "datos cargados (BankingData) y por tanto se puede calcular/mostrar. "
                "Permite a la UI distinguir 'sin dato para este período' de un error y "
                "guiar al usuario al último período disponible de esa entidad.",
)
async def get_bank_periods(
    bank_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(BankingData.period_end)
        .filter(BankingData.bank_id == bank_id)
        .distinct()
        .order_by(BankingData.period_end.desc())
        .all()
    )
    return {"bank_id": bank_id, "periods": [str(r[0]) for r in rows]}


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
    audience: str = Query(
        "comite_credito",
        description="Audiencia para orientar el insight (comite_credito·entidad·"
                    "inversionista·supervisor); una clave desconocida cae al default.",
    ),
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
                axis="banking", audience=audience,
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
    audience: str = Query(
        "comite_credito",
        description="Audiencia para orientar el insight (comite_credito·entidad·"
                    "inversionista·supervisor); una clave desconocida cae al default.",
    ),
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
            entity_ctx = ai_context_entity(detail)
            pubs = publication_prompt_context(db, sector="banca")
            if pubs:
                entity_ctx["contexto_oficial_bcrd"] = pubs
            res = await narrative_engine.generate(
                entity_ctx, template="entity_rating", mode="detailed",
                axis="banking", audience=audience,
            )
            detail["ai_insight"] = {
                "text": res.text,
                "model_used": res.model_used,
                "from_cache": res.from_cache,
            }
        except Exception as e:  # noqa: BLE001 — AI is best-effort; never break the drill-down
            logger.warning("AI insight de entidad no disponible para %s: %s", bank_id, e)

    return detail


# ─── AI insight cards (comparative · sector · scenario) ──────────


@router.post(
    "/insight/compare",
    summary="Análisis comparativo (IA)",
    description="Insight de IA comparando 2–4 entidades (ratings + sub-componentes).",
)
async def compare_insight(
    body: Dict[str, Any] = Body(..., examples=[{"bank_ids": ["id1", "id2"], "period_end": "2025-12-31"}]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bank_ids = body.get("bank_ids") or []
    if not isinstance(bank_ids, list) or len(bank_ids) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 bank_ids.")
    period_end = body.get("period_end")
    pe = None
    if period_end:
        try:
            pe = date.fromisoformat(period_end)
        except ValueError:
            pe = None

    entidades: List[Dict[str, Any]] = []
    for bid in bank_ids[:4]:
        bank = db.query(Bank).filter_by(id=bid).first()
        if not bank:
            continue
        q = db.query(RatingResult).filter_by(bank_id=bid, model_type=ModelType.deterministic)
        if pe is not None:
            q = q.filter(RatingResult.period_end == pe)
        rr = q.order_by(RatingResult.period_end.desc()).first()
        if not rr:
            continue
        entidades.append({
            "nombre": bank.name,
            "tipo": bank.bank_type.value if bank.bank_type else None,
            "rating": rr.rating_tier,
            "score": float(rr.overall_score),
            "sub_componentes": {
                "solidez": float(rr.solidez_score or 0),
                "calidad": float(rr.calidad_score or 0),
                "eficiencia": float(rr.eficiencia_score or 0),
                "liquidez": float(rr.liquidez_score or 0),
                "diversificacion": float(rr.diversificacion_score or 0),
            },
        })
    if len(entidades) < 2:
        raise HTTPException(status_code=404, detail="No hay calificaciones suficientes para comparar.")

    ctx = {"periodo": period_end or "último disponible", "entidades": entidades}
    ai = await _ai_insight(ctx, "comparative") if body.get("with_ai", True) else None
    return {"entities": [e["nombre"] for e in entidades], "ai_insight": ai}


@router.get(
    "/insight/sector",
    summary="Panorama del sector (IA)",
    description="Insight de IA sobre el panorama del sector (distribución de ratings, líderes y rezagadas).",
)
async def sector_insight(
    entity_type: Optional[str] = Query(None, description="Tipo de entidad (vacío = todo el sistema)"),
    period_end: Optional[str] = Query(None, description="Período (YYYY-MM-DD); por defecto el último"),
    with_ai: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pe = None
    if period_end:
        try:
            pe = date.fromisoformat(period_end)
        except ValueError:
            pe = None
    if pe is None:
        pe = db.query(func.max(RatingResult.period_end)).filter(
            RatingResult.model_type == ModelType.deterministic).scalar()
    if pe is None:
        raise HTTPException(status_code=404, detail="No hay calificaciones.")

    rows = (
        db.query(RatingResult, Bank)
        .join(Bank, Bank.id == RatingResult.bank_id)
        .filter(RatingResult.period_end == pe, RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    if entity_type:
        rows = [(rr, b) for rr, b in rows if b.bank_type and b.bank_type.value == entity_type]
    if not rows:
        raise HTTPException(status_code=404, detail="Sin calificaciones para el sector/período.")

    scores = [float(rr.overall_score) for rr, _ in rows]
    by_tier: Dict[str, int] = {}
    for rr, _ in rows:
        by_tier[rr.rating_tier] = by_tier.get(rr.rating_tier, 0) + 1
    ranked = sorted(rows, key=lambda x: float(x[0].overall_score), reverse=True)
    avg = round(sum(scores) / len(scores), 2)
    ctx = {
        "periodo": str(pe),
        "tipo": entity_type or "todo el sistema financiero",
        "n_entidades": len(rows),
        "score_promedio": avg,
        "score_min": round(min(scores), 2),
        "score_max": round(max(scores), 2),
        "distribucion_rating": by_tier,
        "lideres": [{"nombre": b.name, "score": float(rr.overall_score), "rating": rr.rating_tier} for rr, b in ranked[:5]],
        "rezagadas": [{"nombre": b.name, "score": float(rr.overall_score), "rating": rr.rating_tier} for rr, b in ranked[-3:]],
    }
    pubs = publication_prompt_context(db, sector="banca")
    if pubs:
        ctx["contexto_oficial_bcrd"] = pubs
    ai = await _ai_insight(ctx, "sector_outlook") if with_ai else None
    return {"period_end": str(pe), "entity_type": entity_type, "n": len(rows),
            "score_promedio": avg, "ai_insight": ai}


@router.post(
    "/insight/scenario",
    summary="Lectura del escenario (IA)",
    description="Insight de IA que interpreta un escenario simulado (sub-componentes ajustados).",
)
async def scenario_insight(
    body: Dict[str, Any] = Body(..., examples=[{"sub_components": {"solidez": 80, "calidad": 70, "eficiencia": 60, "liquidez": 65, "diversificacion": 55}, "entity_type": "banca_multiple"}]),
    current_user: User = Depends(get_current_user),
):
    subs = body.get("sub_components")
    if not isinstance(subs, dict) or not subs:
        raise HTTPException(status_code=400, detail="Se requiere 'sub_components'.")
    entity_type = body.get("entity_type")
    weights = get_sub_component_weights(entity_type)
    sim_score = calculate_deterministic_score(subs, weights)
    sim_tier = map_rating_tier(sim_score)
    ctx = {
        "tipo_entidad": entity_type,
        "sub_componentes_simulados": subs,
        "score_simulado": sim_score,
        "rating_simulado": sim_tier,
        "base": body.get("base"),  # optional {sub_components, overall_score}
    }
    ai = await _ai_insight(ctx, "recommendation") if body.get("with_ai", True) else None
    return {"overall_score": sim_score, "rating_tier": sim_tier,
            "tier_color": get_tier_color(sim_tier), "ai_insight": ai}


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
    model: str = Query("deterministic", description="Modelo de rating a mostrar (deterministic | ml). Por defecto el determinista (canónico)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        model_type = ModelType(model)
    except ValueError:
        raise HTTPException(status_code=400, detail="Modelo inválido")

    if period_end:
        try:
            pe = date.fromisoformat(period_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")
        results = (
            db.query(RatingResult, Bank)
            .join(Bank, Bank.id == RatingResult.bank_id)
            .filter(RatingResult.period_end == pe)
            .filter(RatingResult.model_type == model_type)
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
            .filter(RatingResult.model_type == model_type)
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
            .filter(RatingResult.model_type == model_type)
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
    total_ratings = (
        db.query(func.count(RatingResult.id))
        .filter(RatingResult.model_type == ModelType.deterministic)
        .scalar()
    )

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


# ─── Fideicomisos públicos (public trusts) ───────────────────────

@router.get(
    "/trusts",
    summary="Fideicomisos públicos (Índice de Salud)",
    description="Lista de fideicomisos públicos con su Índice de Salud (escala propia, no SDQ).",
)
async def list_trusts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trusts = db.query(Fideicomiso).filter(Fideicomiso.is_active.is_(True)).all()
    out: List[Dict[str, Any]] = []
    for t in trusts:
        score = (
            db.query(FideicomisoHealthScore)
            .filter_by(fideicomiso_id=t.id)
            .order_by(FideicomisoHealthScore.period_end.desc())
            .first()
        )
        data = (
            db.query(FideicomisoData)
            .filter_by(fideicomiso_id=t.id)
            .order_by(FideicomisoData.period_end.desc())
            .first()
        )
        managing = db.query(Bank).filter_by(id=t.fiduciaria_bank_id).first() if t.fiduciaria_bank_id else None
        out.append({
            "id": t.id,
            "name": t.name,
            "segment": (score.segment if score else t.segment),
            "fiduciaria": managing.name if managing else None,
            "period_end": str(score.period_end) if score else None,
            "health": {
                "solvencia": float(score.solvencia_score) if score and score.solvencia_score is not None else None,
                "liquidez": float(score.liquidez_score) if score and score.liquidez_score is not None else None,
                "sostenibilidad": float(score.sostenibilidad_score) if score and score.sostenibilidad_score is not None else None,
                "overall": float(score.overall_score) if score and score.overall_score is not None else None,
                "band": score.health_band if score else "N/D",
            },
            "financials": {
                "activos_totales": float(data.activos_totales) if data and data.activos_totales is not None else None,
                "patrimonio_fideicomitido": float(data.patrimonio_fideicomitido) if data and data.patrimonio_fideicomitido is not None else None,
                "pasivos_totales": float(data.pasivos_totales) if data and data.pasivos_totales is not None else None,
                "resultado_periodo": float(data.resultado_periodo) if data and data.resultado_periodo is not None else None,
                "ingresos_operacionales": float(data.ingresos_operacionales) if data and data.ingresos_operacionales is not None else None,
            } if data else None,
        })
    # Sort by overall health desc (N/D last)
    out.sort(key=lambda x: (x["health"]["overall"] is None, -(x["health"]["overall"] or 0)))
    return {"trusts": out, "count": len(out)}


# ─── Market concentration (system-level: CR5/CR10/HHI of the EIF) ─

@router.get(
    "/market-concentration",
    summary="Concentración de mercado (CR10 de las EIF)",
    description="CR5/CR10/HHI del universo EIF por activos/depósitos/cartera. Métrica de estructura de mercado (no es input del rating por banco).",
)
async def market_concentration(
    period_end: Optional[str] = Query(None, description="Período (YYYY-MM-DD); por defecto el último"),
    metric: str = Query("activos", description="activos | depositos | cartera"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.banking_score.scoring.market_concentration import compute_market_concentration

    pe = None
    if period_end:
        try:
            pe = date.fromisoformat(period_end)
        except ValueError:
            pe = None
    try:
        return compute_market_concentration(db, period_end=pe, metric=metric)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Validación / Backtest del rating (T4) ──────────────────────

@router.get(
    "/validation/backtest",
    summary="Backtest de discriminación del rating",
    description="Reporte de validación (Gini + curva de distress por tier). Lee el último cálculo persistido.",
)
async def get_backtest_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json
    from shared.settings.models import AppSetting
    from modules.banking_score.operations import BACKTEST_REPORT_KEY

    row = db.query(AppSetting).filter(AppSetting.key == BACKTEST_REPORT_KEY).first()
    if row and row.value:
        try:
            return {"computed": True, **json.loads(row.value)}
        except (ValueError, TypeError):
            pass
    return {
        "computed": False,
        "message": "El backtest aún no se ha calculado. Genéralo desde la consola de operación o con 'Regenerar'.",
    }


@router.post(
    "/validation/backtest/run",
    summary="Recalcular el backtest (admin)",
    description="Dispara el recálculo del backtest en segundo plano y persiste el reporte.",
)
async def run_backtest(
    current_user: User = Depends(get_current_user),
):
    from shared.auth.models import UserRole
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    # Ensure the banking operations are registered before triggering.
    import modules.banking_score.operations  # noqa: F401
    from shared import operations
    return operations.trigger("backtest", origin="manual", user_id=current_user.id)
