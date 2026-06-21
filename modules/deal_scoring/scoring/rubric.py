"""Deal Scoring — rúbrica declarada y transparente (DEAL-Agent-003, etapa cold-start).

NO es el modelo XGBoost del spec (eso requiere ~labels validados suficientes; ver
`docs/Modelos Propietarios/DEAL_SCORING_Datos_Entrenamiento_Decision.md`). Mientras se
cosecha el dataset, esta rúbrica entrega un score 0-100 EXPLICABLE que **ancla a la
inteligencia real de los 7 ejes** de la plataforma — no pesos arbitrarios:

  - `market_validation`     ← IAI del sector (atractivo del sector en RD) si el analista no lo da
  - `regulatory_readiness`  ← IRMP del país (riesgo regulatorio/político) si el analista no lo da
  - factor `climate`        ← IRC del país (resiliencia climática)

El score es un **índice de cierre/atractivo del deal**, NO una probabilidad (eso
implicaría un modelo entrenado). Toda salida lleva el badge "rúbrica declarada".

Función pura (sin DB, sin imports de otros módulos): recibe las features del deal + los
*anchors* ya leídos (IRMP/IRC/IAI). La composición cross-eje vive en `app/` (raíz de
composición), igual que el Market Brief.
"""
from typing import Any, Dict, Optional

# ── Mapeos de dominio (para que app/ lea el eje correcto) ──────────

# Sector del deal (taxonomía del spec) → slug de sector BCRD (para el IAI, RD).
SECTOR_TO_BCRD: Dict[str, str] = {
    "real_estate": "construccion",
    "tourism": "turismo",
    "mining_energy": "mineria",
    "technology": "comunicaciones",
    "fintech": "financiero",
    "agriculture": "agropecuario",
    "cpg": "manufactura_local",
}

# País del deal (ISO-2) → ISO-3 del panel IRC (clima). Fuera del panel → None.
ISO2_TO_ISO3: Dict[str, str] = {
    "DO": "DOM", "CO": "COL", "MX": "MEX", "PA": "PAN", "CR": "CRI", "GT": "GTM",
    "JM": "JAM", "HT": "HTI", "SV": "SLV", "HN": "HND", "NI": "NIC", "EC": "ECU",
    "PE": "PER", "BO": "BOL", "CL": "CHL", "VE": "VEN",
}

# ── Pesos de la rúbrica (doctrina declarada) ──────────────────────
WEIGHTS: Dict[str, float] = {
    "promoter": 0.18,     # promoter_track_record (juicio de analista)
    "financial": 0.18,    # financial_quality (analista)
    "market": 0.16,       # market_validation, o IAI del sector (anclado)
    "regulatory": 0.16,   # regulatory_readiness, o IRMP del país (anclado)
    "stage": 0.20,        # etapa del deal (predictor estructural fuerte)
    "climate": 0.04,      # IRC del país (eje, menor)
    "momentum": 0.08,     # días desde el primer contacto
}

_STAGE_SCORE = {"initial": 25.0, "due_diligence": 50.0, "term_sheet": 72.0, "legal": 90.0}


def _stage_score(stage: Optional[str]) -> Optional[float]:
    return _STAGE_SCORE.get((stage or "").strip().lower())


def _momentum_score(days: Optional[int]) -> Optional[float]:
    """Fresco = más probable que esté vivo. Stale = se enfría."""
    if days is None:
        return None
    d = float(days)
    if d < 30:
        return 90.0
    if d < 90:
        return 70.0
    if d < 180:
        return 50.0
    if d < 365:
        return 35.0
    return 20.0


def _irmp_to_regulatory(irmp: Optional[float]) -> Optional[float]:
    """IRMP (mayor = menor riesgo) mapea directo a 'regulatory_readiness' 0-100."""
    return None if irmp is None else max(0.0, min(100.0, float(irmp)))


def compute_deal_score(features: Dict[str, Any], anchors: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """Rúbrica pura. *features* = inputs del deal; *anchors* = {country_irmp, sector_iai,
    country_irc} ya leídos (o None). Devuelve score 0-100 + drivers explicables.

    Componente faltante (analista y eje ausentes) → se omite y su peso se redistribuye
    proporcionalmente entre los presentes (no se penaliza por dato faltante)."""
    def g(k):
        # Señales de analista 0-100: se acotan al rango para que el score sea siempre
        # un índice honesto 0-100 (los anchors y stage/momentum ya vienen acotados).
        v = features.get(k)
        return max(0.0, min(100.0, float(v))) if isinstance(v, (int, float)) else None

    # Cada componente: (valor 0-100 | None, origen)
    comps: Dict[str, Dict[str, Any]] = {}

    comps["promoter"] = {"value": g("promoter_track_record"), "source": "analista"}
    comps["financial"] = {"value": g("financial_quality"), "source": "analista"}

    mv = g("market_validation")
    if mv is not None:
        comps["market"] = {"value": mv, "source": "analista"}
    else:
        comps["market"] = {"value": anchors.get("sector_iai"), "source": "IAI sector (eje)"}

    rr = g("regulatory_readiness")
    if rr is not None:
        comps["regulatory"] = {"value": rr, "source": "analista"}
    else:
        comps["regulatory"] = {"value": _irmp_to_regulatory(anchors.get("country_irmp")),
                               "source": "IRMP país (eje)"}

    comps["stage"] = {"value": _stage_score(features.get("deal_stage")), "source": "etapa"}
    comps["climate"] = {"value": anchors.get("country_irc"), "source": "IRC país (eje)"}
    comps["momentum"] = {"value": _momentum_score(features.get("days_since_first_contact")),
                         "source": "días desde contacto"}

    # Promedio ponderado sobre los componentes presentes (redistribuye pesos faltantes).
    present = {k: c for k, c in comps.items() if c["value"] is not None}
    wsum = sum(WEIGHTS[k] for k in present) or 1.0
    score = sum(WEIGHTS[k] * present[k]["value"] for k in present) / wsum

    # Drivers ordenados por contribución (peso normalizado × valor).
    factors = []
    for k, c in present.items():
        wnorm = WEIGHTS[k] / wsum
        factors.append({
            "factor": k,
            "value": round(c["value"], 1),
            "source": c["source"],
            "weight": round(wnorm, 3),
            "contribution": round(wnorm * c["value"], 1),
        })
    factors.sort(key=lambda f: f["contribution"], reverse=True)

    # Confianza honesta: cuántos componentes vienen de juicio de analista (vs eje/faltante).
    n_analyst = sum(1 for c in present.values() if c["source"] == "analista")
    n_missing = len(comps) - len(present)
    if n_analyst >= 3 and n_missing <= 1:
        confidence = "alta"
    elif n_analyst >= 2:
        confidence = "media"
    else:
        confidence = "baja"

    return {
        "score": round(score, 1),
        "confidence": confidence,
        "method": "rúbrica declarada (anclada a IRMP/IAI/IRC)",
        "is_trained_model": False,
        "key_factors": factors,
        "components_present": len(present),
        "components_total": len(comps),
        "anchors_used": {k: v for k, v in anchors.items() if v is not None},
    }
