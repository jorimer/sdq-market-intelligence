"""Deal Scoring — endpoint de scoring (composición cross-eje, raíz app/).

Lee los *anchors* de los ejes (IRMP del país, IRC del país, IAI del sector) vía el
getter de servicio PÚBLICO de cada módulo, llama a la rúbrica pura
(`modules.deal_scoring.scoring.rubric`) y agrega una narrativa de Claude. NO accede a
tablas ajenas en crudo; app/ es la raíz de composición (mismo patrón que el Market Brief).

Esto es la **rúbrica declarada** de cold-start, no el XGBoost del spec.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.deal_scoring.scoring.rubric import (
    ISO2_TO_ISO3, SECTOR_TO_BCRD, WEIGHTS, compute_deal_score,
)

logger = logging.getLogger("sdq.deal_scoring")

router = APIRouter()


def _fetch_anchors(db: Session, country_iso2: Optional[str], sector: Optional[str]) -> Dict[str, Any]:
    """Lee los anchors de los ejes (o None si el país/sector no está cubierto)."""
    irmp = irc = iai = None
    src: Dict[str, str] = {}
    c2 = (country_iso2 or "").strip().upper()

    # IRMP — riesgo regulatorio/político del país (snapshot persistido)
    try:
        from modules.macro_political_risk import service as irmp_svc
        snap = irmp_svc.get_latest(db, c2)
        if snap and snap.irmp_score is not None:
            irmp = float(snap.irmp_score)
            src["country_irmp"] = f"IRMP {c2} {irmp:.1f}"
    except Exception as e:  # noqa: BLE001
        logger.warning("deal anchor IRMP: %s", e)

    # IRC — resiliencia climática del país (ISO-3)
    try:
        from modules.esg_climate import service as esg_svc
        iso3 = ISO2_TO_ISO3.get(c2)
        if iso3:
            s = esg_svc.get_latest(db, iso3)
            if s and s.esg_score is not None:
                irc = float(s.esg_score)
                src["country_irc"] = f"IRC {iso3} {irc:.1f}"
    except Exception as e:  # noqa: BLE001
        logger.warning("deal anchor IRC: %s", e)

    # IAI — atractivo del sector en RD (solo si país RD y sector mapeable)
    try:
        from modules.sector_intel import service as sector_svc
        slug = SECTOR_TO_BCRD.get((sector or "").strip().lower())
        if slug and c2 == "DO":
            sc = sector_svc.get_latest(db, slug)
            if sc and sc.iai_score is not None:
                iai = float(sc.iai_score)
                src["sector_iai"] = f"IAI {slug} {iai:.1f}"
    except Exception as e:  # noqa: BLE001
        logger.warning("deal anchor IAI: %s", e)

    return {"values": {"country_irmp": irmp, "country_irc": irc, "sector_iai": iai}, "sources": src}


async def _narrative(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template="deal_outlook", mode="detailed")
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001
        logger.warning("deal narrative no disponible: %s", e)
        return None


@router.get("/weights", summary="Doctrina de la rúbrica de Deal Scoring")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "weights": WEIGHTS,
        "method": "rúbrica declarada (cold-start), anclada a IRMP/IAI/IRC",
        "is_trained_model": False,
        "anchoring": {
            "regulatory_readiness": "IRMP del país (si el analista no lo provee)",
            "market_validation": "IAI del sector en RD (si el analista no lo provee)",
            "climate": "IRC del país",
        },
        "sector_map": SECTOR_TO_BCRD,
        "note": "El score es un índice de cierre/atractivo, NO una probabilidad. El "
                "XGBoost del spec se activa cuando el dataset cosechado gane el umbral de IC en CV.",
    }


@router.post("/score", summary="Scorear un deal (rúbrica + narrativa IA)")
async def score(
    body: Dict[str, Any] = Body(..., examples=[{
        "deal_name": "Ejemplo", "deal_type": "capital_raise", "sector": "fintech",
        "country": "DO", "deal_stage": "due_diligence", "deal_size_usd": 5000000,
        "equity_required_pct": 30, "promoter_track_record": 75, "financial_quality": 68,
        "market_validation": None, "regulatory_readiness": None, "days_since_first_contact": 45,
        "with_ai": True,
    }]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body inválido.")
    country = body.get("country")
    sector = body.get("sector")
    anchors = _fetch_anchors(db, country, sector)
    result = compute_deal_score(body, anchors["values"])
    result["anchor_sources"] = anchors["sources"]

    ai = None
    if body.get("with_ai", True):
        ctx = {
            "deal": {
                "nombre": body.get("deal_name"), "tipo": body.get("deal_type"),
                "sector": sector, "pais": country, "etapa": body.get("deal_stage"),
                "tamano_usd": body.get("deal_size_usd"), "equity_pct": body.get("equity_required_pct"),
            },
            "score": result["score"], "confianza": result["confidence"],
            "drivers": result["key_factors"],
            "contexto_ejes": anchors["sources"],
            "metodo": result["method"],
        }
        ai = await _narrative(ctx)
    result["ai_insight"] = ai
    return result
