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
from modules.banking_score.scoring.ttm import attach_ttm
from modules.banking_score.ml.xgboost_model import xgboost_model
from modules.banking_score.scoring.indicator_detail import ai_context, build_indicator_detail
from modules.banking_score.scoring.entity_insight import ai_context_entity, build_entity_insight
from shared.publications.service import publication_prompt_context
from modules.banking_score.scoring.perfil_sdq import banda_resiliencia, calcular_ejes
from modules.banking_score.scoring.weights import (
    WEIGHT_PROFILES,
    get_sub_component_weights,
)

logger = logging.getLogger("sdq.api.scoring")

router = APIRouter()


async def _ai_insight(context: Dict[str, Any], template: str, *,
                      axis: Optional[str] = None,
                      audience: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Generate a Claude narrative from *context* using *template*; best-effort
    (returns None on any failure so the endpoint never breaks). Con *axis* activa la
    ruta cerebro (Barra de Insight + doctrina + guardrail) — usar siempre que haya thin."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template=template, mode="detailed",
                                              axis=axis, audience=audience)
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
    tipo = body.get("entity_type")
    weights = get_sub_component_weights(tipo)
    overall = calculate_deterministic_score(subs, weights)
    # Perfil SDQ sobre la simulación: un escenario también se lee en DOS ejes. La banda de
    # Ejecución NO se emite acá — es relativa al panel comparable (cuartiles por tipo) y un
    # escenario hipotético no tiene panel. Se devuelve el score y se declara por qué.
    ejes = calcular_ejes(subs, tipo)
    return {
        "sub_components": subs,
        "overall_score": overall,
        "ejecucion": ejes["ejecucion"],
        "resiliencia": ejes["resiliencia"],
        "banda_resiliencia": banda_resiliencia(ejes["resiliencia"]),
        "banda_ejecucion": None,
        "nota_banda_ejecucion": (
            "La banda de Ejecución es RELATIVA a los cuartiles del panel comparable; un "
            "escenario hipotético no pertenece a un panel, así que se devuelve el score sin "
            "banda en vez de compararlo contra cortes que no le aplican."),
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
        # Ventana móvil de 12 meses para ROA/ROE: el motor es puro (sin DB) y la necesita
        # como insumo. Sin ella esos dos indicadores se declaran NO disponibles.
        attach_ttm(db, data)
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
            ml_ejes = xgboost_model.predict(flat_scores)
        except Exception as e:
            logger.error(f"Error en predicción ML para {bank_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Error en predicción ML: {e}")
        # El ML predice los DOS EJES; sub-componentes e indicadores (sus insumos) se
        # conservan para explicabilidad. La banda de Ejecución NO se deriva acá: es
        # relativa al panel comparable y esta ruta puntúa UNA entidad sin panel a la vista.
        result["ejecucion"] = ml_ejes["ejecucion"]
        result["resiliencia"] = ml_ejes["resiliencia"]
        result["banda_resiliencia"] = banda_resiliencia(ml_ejes["resiliencia"])
        result["banda_ejecucion"] = None
        result["model_version"] = xgboost_model.version or result.get("model_version")
        model_type = ModelType.ml
    result["model"] = model

    # Persist RatingResult (deterministic and ml coexist via the unique constraint)
    existing = db.query(RatingResult).filter_by(
        bank_id=bank_id, period_end=pe, model_type=model_type,
    ).first()

    if existing:
        existing.overall_score = result["overall_score"]
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
    logger.info("Scoring completado: %s | %s → Ejec %s · Resil %s", bank.name, period_end,
                result.get("banda_ejecucion"), result.get("banda_resiliencia"))

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
        # Perfil SDQ: dos ejes, no un símbolo. La columna `rating_tier` queda en la base
        # con su histórico como LINAJE; las filas nuevas ya no la llevan.
        "ejecucion": float(result.ejecucion_score) if result.ejecucion_score is not None else None,
        "banda_ejecucion": result.banda_ejecucion,
        "resiliencia": float(result.resiliencia_score) if result.resiliencia_score is not None else None,
        "banda_resiliencia": result.banda_resiliencia,
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
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
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
                ai_context(detail), template="indicator_insight",
                mode="deep" if deep else "detailed",
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
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
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
                entity_ctx, template="entity_rating",
                mode="deep" if deep else "detailed",
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
            "banda_ejecucion": rr.banda_ejecucion,
            "banda_resiliencia": rr.banda_resiliencia,
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
    ai = (await _ai_insight(ctx, "banking_compare", axis="banking", audience="comite_credito")
          if body.get("with_ai", True) else None)
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
        b = rr.banda_resiliencia
        if b:
            by_tier[b] = by_tier.get(b, 0) + 1
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
        "lideres": [{"nombre": b.name, "score": float(rr.overall_score),
                     "banda_ejecucion": rr.banda_ejecucion,
                     "banda_resiliencia": rr.banda_resiliencia} for rr, b in ranked[:5]],
        "rezagadas": [{"nombre": b.name, "score": float(rr.overall_score),
                       "banda_ejecucion": rr.banda_ejecucion,
                       "banda_resiliencia": rr.banda_resiliencia} for rr, b in ranked[-3:]],
    }
    pubs = publication_prompt_context(db, sector="banca")
    if pubs:
        ctx["contexto_oficial_bcrd"] = pubs
    ai = (await _ai_insight(ctx, "banking_system", axis="banking", audience="comite_credito")
          if with_ai else None)
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
    sim_ejes = calcular_ejes(subs, entity_type)
    ctx = {
        "tipo_entidad": entity_type,
        "sub_componentes_simulados": subs,
        "score_simulado": sim_score,
        # El contexto que ve la IA también va en dos ejes: si le pasáramos el símbolo único
        # escribiría sobre él, y la narrativa volvería a reintroducir la notación que la
        # superficie acaba de retirar.
        "ejecucion_simulada": sim_ejes["ejecucion"],
        "resiliencia_simulada": sim_ejes["resiliencia"],
        "base": body.get("base"),  # optional {sub_components, overall_score}
    }
    ai = (await _ai_insight(ctx, "banking_recommendation", axis="banking", audience="entidad")
          if body.get("with_ai", True) else None)
    return {"overall_score": sim_score,
            "ejecucion": sim_ejes["ejecucion"], "resiliencia": sim_ejes["resiliencia"],
            "banda_resiliencia": banda_resiliencia(sim_ejes["resiliencia"]),
            "banda_ejecucion": None, "ai_insight": ai}


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
            "ejecucion": float(r.ejecucion_score) if r.ejecucion_score is not None else None,
            "banda_ejecucion": r.banda_ejecucion,
            "resiliencia": float(r.resiliencia_score) if r.resiliencia_score is not None else None,
            "banda_resiliencia": r.banda_resiliencia,
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

# Etiquetas legibles para la prosa de metodología. Un tipo sin etiqueta usa su propio
# valor: preferimos un nombre feo a omitir un tipo del texto.
_TIPO_LABEL = {
    "banca_multiple": "banca múltiple",
    "cambiaria": "intermediación cambiaria",
    "banco_ahorro_credito": "bancos de ahorro y crédito",
    "corporacion_credito": "corporaciones de crédito",
    "aap": "asociaciones de ahorros y préstamos",
    "fiduciaria": "fiduciarias",
}

# Bajo este umbral la mediana de un tipo se apoya en muy pocas entidades y no sirve para
# sostener una afirmación de metodología (§4.2, misma lógica del panel chico).
_MIN_TIPO_PARA_CITAR = 5


def _medianas_ejecucion_por_tipo(rankings: List[Dict]) -> Dict[str, Dict]:
    """Mediana de Ejecución por tipo de entidad, computada del panel que se acaba de servir."""
    por_tipo: Dict[str, List[float]] = {}
    for r in rankings:
        if r.get("bank_type") and r.get("ejecucion") is not None:
            por_tipo.setdefault(r["bank_type"], []).append(float(r["ejecucion"]))
    out: Dict[str, Dict] = {}
    for tipo, vals in por_tipo.items():
        vals.sort()
        n = len(vals)
        mediana = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        out[tipo] = {"mediana": round(mediana, 1), "n": n}
    return out


def _frase_brecha_medianas(medianas: Dict[str, Dict]) -> str:
    """Frase que cita la brecha real entre los dos tipos más separados, o cadena vacía.

    Devuelve "" cuando no hay dos tipos con panel suficiente: sin evidencia no se afirma.
    """
    citables = {t: m for t, m in medianas.items() if m["n"] >= _MIN_TIPO_PARA_CITAR}
    if len(citables) < 2:
        return ""
    orden = sorted(citables.items(), key=lambda kv: kv[1]["mediana"])
    bajo, alto = orden[0], orden[-1]
    return (
        f": la mediana de Ejecución es {bajo[1]['mediana']} en "
        f"{_TIPO_LABEL.get(bajo[0], bajo[0])} y {alto[1]['mediana']} en "
        f"{_TIPO_LABEL.get(alto[0], alto[0])}"
    )


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

    # Período más reciente del conjunto: ancla para marcar filas con rating rezagado.
    # El ranking global mezcla tipos de entidad NO comparables (banca múltiple, cambiarias,
    # ahorro y crédito, …); ``rank_in_type`` da la posición dentro del propio tipo para no
    # inducir a leer una casa de cambio como "más sólida" que un banco múltiple. ``stale``
    # marca ratings viejos frente al corte más fresco (aditivo, no muta el score).
    latest_pe = max((rr.period_end for rr, _ in results), default=None)
    STALE_MONTHS = 9  # ~3 trimestres detrás del corte más reciente
    _type_counter: Dict[str, int] = {}

    def _months_behind(pe) -> Optional[int]:
        if latest_pe is None or pe is None:
            return None
        return (latest_pe.year - pe.year) * 12 + (latest_pe.month - pe.month)

    rankings = []
    for i, (rr, bank) in enumerate(results):
        btype = bank.bank_type.value if bank.bank_type else None
        _type_counter[btype] = _type_counter.get(btype, 0) + 1
        mb = _months_behind(rr.period_end)
        rankings.append({
            "rank": i + 1,
            "rank_in_type": _type_counter[btype],
            "bank_id": rr.bank_id,
            "bank_name": bank.name,
            "bank_type": btype,
            "period_end": str(rr.period_end),
            "months_behind": mb,
            "stale": (mb is not None and mb >= STALE_MONTHS),
            "overall_score": float(rr.overall_score),
            # Perfil SDQ — los dos ejes que reemplazan la lectura del símbolo único.
            "ejecucion": float(rr.ejecucion_score) if rr.ejecucion_score is not None else None,
            "banda_ejecucion": rr.banda_ejecucion,
            "resiliencia": float(rr.resiliencia_score) if rr.resiliencia_score is not None else None,
            "banda_resiliencia": rr.banda_resiliencia,
        })
    # La justificación de por qué la banda de Ejecución es relativa se apoya en la brecha
    # de medianas entre tipos de entidad. Esa brecha es un HECHO DEL PANEL: se computa acá
    # y el texto la cita, nunca al revés — un número escrito en la prosa queda obsoleto en
    # la primera recalibración y pasa a afirmar algo falso con tono de metodología.
    _medianas = _medianas_ejecucion_por_tipo(rankings)
    _brecha = _frase_brecha_medianas(_medianas)

    return {
        "rankings": rankings, "count": len(rankings),
        "period_end": period_end or "latest",
        "latest_period_end": str(latest_pe) if latest_pe else None,
        "notacion": {
            "primaria": "Perfil SDQ — Ejecución y Resiliencia, dos ejes independientes.",
            # notacion-heredada-ok: el literal DECLARA la retirada de la notación; nombrarla
            # es su función. Sin esto el consumidor de la API no sabe qué pasó con la columna.
            "notacion_retirada": (
                "La notación de letras (SDQ-AAA…SDQ-D) YA NO SE PUBLICA. Usaba la gramática "
                "de una calificadora sin serlo, y `SDQ-D` cubría 45 puntos de rango "
                "aplicándose a entidades que operan con normalidad. La columna se conserva "
                "en la base como linaje del dato, no como superficie."),
        },
        "metodologia": {
            "banda_resiliencia": (
                "ABSOLUTA: cortes fijos 75/60/45, los mismos en los cuatro sectores."),
            "banda_ejecucion": (
                "RELATIVA AL TIPO DE ENTIDAD: cuartiles del panel comparable, no cortes "
                "fijos. En banca no existe un ancla económica de eficiencia —como sí lo son "
                "el mínimo regulatorio en solvencia o el breakeven en seguros— y la "
                "rentabilidad difiere por MODELO DE NEGOCIO, no solo por desempeño"
                + _brecha +
                ". Con cortes fijos, casi toda la intermediación cambiaria caería en "
                "\"Deficiente\" por su estructura de capital —están sobrecapitalizadas, lo que "
                "deprime el ROE de forma mecánica— y no por ser ineficientes."),
            "medianas_ejecucion_por_tipo": _medianas,
            "como_leerla": (
                "\"Sobresaliente\" significa \"en el cuartil superior de su tipo de entidad\", "
                "no un nivel absoluto. Por eso cada fila trae su posición dentro del grupo."),
        },
    }


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
    from shared.auth.models import UserRole, role_satisfies
    if not role_satisfies(current_user.role, UserRole.admin):
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    # Ensure the banking operations are registered before triggering.
    import modules.banking_score.operations  # noqa: F401
    from shared import operations
    return operations.trigger("backtest", origin="manual", user_id=current_user.id)


@router.get(
    "/alerts",
    summary="Alertas de alerta temprana (sistema)",
    description="Señales de monitoreo por banco al último período, ancladas a los precursores "
                "de la crisis RD 2003 (crecimiento anómalo, fondeo caro, brecha de provisiones, "
                "salto de morosidad, solvencia cerca del piso, estrés de liquidez, concentración). "
                "Complemento del rating, no un veredicto.",
)
async def get_system_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.banking_score.early_warning import compute_alerts
    return compute_alerts(db)


@router.get(
    "/{bank_id}/alerts",
    summary="Alertas de alerta temprana (un banco)",
    description="Las alertas de monitoreo del banco indicado en el último período (lista vacía "
                "si no tiene banderas activas).",
)
async def get_bank_alerts(
    bank_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.banking_score.early_warning import compute_alerts
    block = compute_alerts(db)
    entry = next((b for b in block["banks"] if b["bank_id"] == bank_id), None)
    return {"period": block["period"], "bank_id": bank_id,
            "alerts": entry["alerts"] if entry else [],
            "max_severity": entry["max_severity"] if entry else None}
