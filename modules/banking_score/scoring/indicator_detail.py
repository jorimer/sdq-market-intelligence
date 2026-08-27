"""Per-indicator drill-down: metadata, interpretation, trend, and peer stats.

Backs the indicator drill-down endpoint. Given a bank and one of the 19 scoring
indicators, it assembles: the latest value + qualitative band, a chronological
trend (from the stored ``RatingResult.indicator_details`` JSON, no re-ingest), and
the entity's position vs its peers (whole sector + same entity type) for that
indicator. The AI insight is generated separately (async) in the API layer using
this object as context.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult

# ── Indicator metadata ───────────────────────────────────────────
# label: human (ES) name · sub: sub-component · unit: raw unit ·
# direction: how to read the raw value (higher/lower/target/bell) · que: what it measures ·
# optimo: for `target` indicators, the peak of the curve as a NUMBER.
#
# `optimo` existía solo dentro del texto de `que` ("óptimo ~80%"), que es prosa y no se puede
# computar. Sin él, la narrativa no puede decir de qué lado del óptimo cayó el valor y el
# modelo lo deduce del SCORE — que en un indicador de óptimo intermedio es alto a ambos lados.
# Así salió el LTD de BPD: 92.45% con score 98.62 se narró como «destina proporcionalmente
# MENOS de cada peso captado» y «preserva margen para atender retiros», la glosa de un LTD
# BAJO, contradiciendo a la §7 del mismo informe. Espeja las curvas de `engine.py`.
INDICATOR_META: Dict[str, Dict[str, Any]] = {
    # Solidez
    "solvencia": {"label": "Índice de solvencia", "sub": "solidez", "unit": "%", "direction": "higher",
                  "que": "Patrimonio técnico / activos ponderados por riesgo. Suficiencia de capital."},
    "tier1_ratio": {"label": "Solvencia de capital primario", "sub": "solidez", "unit": "%", "direction": "higher",
                    "que": "Capital primario / APR. Calidad del capital de mayor absorción de pérdidas."},
    # NO es el ratio de apalancamiento de Basilea, aunque se llamó así hasta 2026-08-26. El
    # de Basilea es deliberadamente NO ponderado por riesgo —ése es su propósito: ser el
    # contrapeso de los índices de solvencia—, y el denominador que sirve el SIB acá son
    # «ACTIVOS Y CONTINGENTES PONDERADOS POR RIESGO CREDITICIO Y RIESGO DE MERCADO». Es un
    # tercer índice de adecuación de capital, y el rótulo tiene que decirlo: en un documento
    # de rating, llamar Basilea a algo que no lo es lo nota cualquier analista.
    "leverage": {"label": "Capital primario / activos ponderados", "sub": "solidez",
                 "unit": "%", "direction": "higher",
                 "que": ("Capital primario / activos y contingentes ponderados por riesgo. "
                         "Comparte numerador con la solvencia de capital primario y "
                         "denominador con el índice de solvencia: coincide con éste cuando "
                         "la entidad no tiene capital secundario.")},
    "cobertura_provisiones": {"label": "Cobertura de cartera vencida", "sub": "solidez", "unit": "%", "direction": "higher",
                              "que": "Provisiones / cartera vencida >90d. Colchón ante pérdidas crediticias."},
    "patrimonio_activos": {"label": "Patrimonio / activos", "sub": "solidez", "unit": "%", "direction": "higher",
                           "que": "Capitalización contable."},
    # Calidad
    "morosidad": {"label": "Morosidad >90 días", "sub": "calidad", "unit": "%", "direction": "lower",
                  "que": "Cartera vencida >90d / cartera bruta (menor es mejor)."},
    "pct_cartera_a": {"label": "Cartera vigente", "sub": "calidad", "unit": "%", "direction": "higher",
                      "que": "Cartera vigente / bruta. Proporción de cartera al día."},
    # sujeto-ok: la población viaja en `que` («los 10 mayores DEUDORES / cartera»), y el
    # contexto la sirve como "mide" en el mismo bloque que el valor (_semantica_indicadores).
    "concentracion_top10": {"label": "Concentración top-10", "sub": "calidad", "unit": "%", "direction": "lower",
                            "que": "Suma de los 10 mayores deudores / cartera (menor es mejor)."},
    "hhi_sectorial": {"label": "HHI sectorial de cartera", "sub": "calidad", "unit": "índice", "direction": "lower",
                      "que": "Concentración de la cartera por sector económico (menor es más diversificado)."},
    "castigos_pct": {"label": "Castigos", "sub": "calidad", "unit": "%", "direction": "lower",
                     "que": "Castigos / cartera total. Pérdidas dadas de baja (menor es mejor)."},
    "exposicion_re": {"label": "Exposición inmobiliaria", "sub": "calidad", "unit": "%", "direction": "target",
                      "optimo": 40.0,
                      "que": "Cartera hipotecaria / cartera total (óptimo ~40%)."},
    "migracion": {"label": "Migración de cartera A", "sub": "calidad", "unit": "%", "direction": "target",
                  "optimo": 0.0,
                  "que": "Cambio de la cartera categoría A vs el período previo (estabilidad es mejor)."},
    # NO es un octavo indicador de calidad: es el PROMEDIO de los siete de arriba
    # (`calc_composite_calidad`). Faltaba en este registro, así que salía con el fallback
    # —"Composite Calidad", su clave title-cased— y en una fila igual a las demás, como si
    # fuera evidencia adicional. Un lector cuenta ocho hechos y hay siete.
    #
    # Incluirlo en el promedio de la dimensión es matemáticamente NEUTRO —agregar la media de
    # un conjunto al conjunto no cambia la media—, así que esto NO mueve ningún score: es un
    # problema de lectura, no de cálculo. Por eso se rotula en vez de removerse.
    "composite_calidad": {"label": "Calidad de activos (resumen de los 7)", "sub": "calidad",
                          "unit": "", "direction": "higher",
                          "que": ("Promedio de los siete indicadores de calidad de activos. "
                                  "NO es una medición independiente: resume a las anteriores, "
                                  "así que no debe citarse como evidencia adicional junto a "
                                  "ellas.")},
    # Eficiencia
    # NO son «anualizados»: usan la ventana móvil de DOCE MESES, que se adoptó justamente
    # para NO anualizar. Anualizar multiplicaba un trimestre por 12/mes y el panel refutó ese
    # supuesto —el Q1 concentra una mediana del 9,9 % de la utilidad del año—, así que el
    # rótulo viejo describía el método que se abandonó. Ver `scoring/ttm.py`.
    "roa": {"label": "ROA (12 meses móviles)", "sub": "eficiencia", "unit": "%",
            "direction": "higher",
            "que": ("Utilidad de los últimos doce meses / activos promedio. Rentabilidad "
                    "sobre activos, con ventana móvil: NO es un trimestre anualizado.")},
    "roe": {"label": "ROE (12 meses móviles)", "sub": "eficiencia", "unit": "%",
            "direction": "higher",
            "que": ("Utilidad de los últimos doce meses / patrimonio. Rentabilidad sobre "
                    "capital, con ventana móvil: NO es un trimestre anualizado.")},
    "margen_financiero": {"label": "Margen de intermediación", "sub": "eficiencia", "unit": "%", "direction": "higher",
                          "que": "Margen de intermediación neto. Spread del negocio de intermediación."},
    "cost_to_income": {"label": "Eficiencia operativa (cost-to-income)", "sub": "eficiencia", "unit": "%", "direction": "lower",
                       "que": "Gastos operativos / ingreso operativo pre-provisión (margen "
                              "financiero bruto + otros ingresos operacionales). Definición "
                              "comparable a calificadoras internacionales; menor es mejor."},
    # Liquidez
    "liquidez_inmediata": {"label": "Liquidez inmediata", "sub": "liquidez", "unit": "%", "direction": "higher",
                           "que": "Caja y valores / pasivos de corto plazo."},
    "ltd": {"label": "Cartera / depósitos (LtD)", "sub": "liquidez", "unit": "%", "direction": "target",
            "optimo": 80.0,
            "que": "Cartera neta / depósitos (óptimo ~80%)."},
    "liquidez_ajustada": {"label": "Liquidez ajustada", "sub": "liquidez", "unit": "%", "direction": "higher",
                          "que": "Activos líquidos / pasivos exigibles."},
    # Diversificación
    # sujeto-ok: `que` nombra la población (la composición de INGRESOS de la entidad)
    "hhi_ingresos": {"label": "HHI de ingresos", "sub": "diversificacion", "unit": "índice", "direction": "lower",
                     "que": "Concentración de las fuentes de ingreso (menor es más diversificado)."},
}

# Non-credit submodels (cambiaria · fiduciaria) expose their own indicator keys as
# sub-component drivers. They are NOT in INDICATOR_META above, so the drill-down used
# to 404 for those entities. Metadata is keyed by entity_type because a few keys mean
# opposite things across submodels (e.g. `diversificacion_ingresos`: a balance proxy
# where higher is better for cambiarias, but an income HHI where lower is better for
# fiduciarias). `roa`/`roe`/`cost_to_income` are reused from INDICATOR_META unchanged.
SUBMODEL_INDICATOR_META: Dict[str, Dict[str, Dict[str, str]]] = {
    "cambiaria": {
        "capitalizacion": {"label": "Capitalización", "sub": "solidez", "unit": "%", "direction": "higher",
                           "que": "Patrimonio / activos. Los agentes cambiarios se fondean con capital; mayor capitalización es más sólido."},
        "apalancamiento": {"label": "Apalancamiento", "sub": "solidez", "unit": "veces", "direction": "lower",
                           "que": "Pasivos exigibles / patrimonio. Apalancamiento del agente (menor es más sólido)."},
        "calidad_activos": {"label": "Calidad de activos", "sub": "calidad", "unit": "%", "direction": "higher",
                            "que": "Activos líquidos / activos. Proporción de activos líquidos vs inmovilizados."},
        "exposicion_credito": {"label": "Exposición a crédito", "sub": "calidad", "unit": "%", "direction": "lower",
                               "que": "Cartera de créditos / activos. Un libro de crédito fuera de la misión cambiaria añade riesgo (menor es mejor)."},
        "cobertura_liquida": {"label": "Cobertura líquida", "sub": "liquidez", "unit": "%", "direction": "higher",
                              "que": "Activos líquidos / pasivos exigibles. Capacidad de operar y liquidar obligaciones."},
        "diversificacion_ingresos": {"label": "Diversificación (proxy)", "sub": "diversificacion", "unit": "ratio", "direction": "higher",
                                     "que": "Proxy de diversificación por equilibrio del balance (el feed EIC no desglosa ingresos): 1 = balance más equilibrado."},
    },
    "fiduciaria": {
        "capitalizacion": {"label": "Capitalización", "sub": "solidez", "unit": "%", "direction": "higher",
                           "que": "Patrimonio / activos. Las fiduciarias son sociedades de servicios fondeadas con capital."},
        "apalancamiento": {"label": "Apalancamiento", "sub": "solidez", "unit": "veces", "direction": "lower",
                           "que": "Pasivos exigibles / patrimonio (menor es más sólido)."},
        "calidad_activos": {"label": "Calidad de activos", "sub": "calidad", "unit": "%", "direction": "higher",
                            "que": "Activos líquidos / activos. Liquidez/productividad de los activos vs inmovilizados."},
        "cobertura_liquida": {"label": "Cobertura líquida", "sub": "liquidez", "unit": "%", "direction": "higher",
                              "que": "Activos líquidos / pasivos circulantes. Capacidad de cubrir obligaciones de corto plazo."},
        "diversificacion_ingresos": {"label": "Diversificación de ingresos", "sub": "diversificacion", "unit": "ratio", "direction": "lower",
                                     "que": "HHI de ingresos (comisiones fiduciarias vs otros). Menor HHI = ingresos más diversificados."},
    },
}


def _meta_for(indicator_key: str, bank: Bank) -> Optional[Dict[str, str]]:
    """Resolve indicator metadata: credit model first, then the entity's submodel
    (cambiaria / fiduciaria) for keys the credit model doesn't define."""
    meta = INDICATOR_META.get(indicator_key)
    if meta is not None:
        return meta
    if bank.bank_type is not None:
        return SUBMODEL_INDICATOR_META.get(bank.bank_type.value, {}).get(indicator_key)
    return None


def _band(score: float) -> str:
    """Qualitative band from a 0–100 score (matches the UI color thresholds)."""
    if score >= 85:
        return "fuerte"
    if score >= 70:
        return "adecuado"
    if score >= 55:
        return "moderado"
    return "débil"


def _interpretation(meta: Dict[str, str], raw: Optional[float], score: float) -> str:
    """One-line, data-grounded reading of the indicator's current level."""
    band = _band(score)
    unit = meta["unit"]
    if not isinstance(raw, (int, float)):
        val = "N/D"
    elif unit == "índice":
        val = f"{raw:.0f}"
    elif unit == "veces":
        val = f"{raw:.2f}×"
    elif unit == "ratio":
        val = f"{raw:.2f}"
    else:
        val = f"{raw:.2f}%"
    return f"Nivel {band} (score {score:.0f}/100). {meta['que']} Valor actual: {val}."


def _percentile(scores: List[float], value: float) -> float:
    """Percentile rank of *value* within *scores* (% of peers at or below it)."""
    if not scores:
        return 0.0
    at_or_below = sum(1 for s in scores if s <= value)
    return round(at_or_below / len(scores) * 100, 1)


def _quantile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 2)


def _peer_stats(scores: List[float], value: float) -> Optional[Dict[str, Any]]:
    """Distribution of peer scores + this entity's position. None if no peers."""
    vals = sorted(s for s in scores if s is not None)
    if not vals:
        return None
    return {
        "n": len(vals),
        "median_score": _quantile(vals, 0.5),
        "p25_score": _quantile(vals, 0.25),
        "p75_score": _quantile(vals, 0.75),
        "percentile": _percentile(vals, value),
    }


def build_indicator_detail(db: Session, bank: Bank, indicator_key: str) -> Optional[Dict[str, Any]]:
    """Assemble the deterministic drill-down (no AI) for one bank × indicator.

    Returns None if the indicator key is unknown or the bank has no ratings.
    """
    meta = _meta_for(indicator_key, bank)
    if meta is None:
        return None

    ratings = (
        db.query(RatingResult)
        .filter(RatingResult.bank_id == bank.id,
                RatingResult.model_type == ModelType.deterministic)
        .order_by(RatingResult.period_end.asc())
        .all()
    )
    if not ratings:
        return None

    def _ind(rr: RatingResult) -> Optional[Dict]:
        details = rr.indicator_details or {}
        return details.get(indicator_key)

    # Chronological trend (only periods where the indicator was available/measured).
    trend: List[Dict[str, Any]] = []
    for rr in ratings:
        d = _ind(rr)
        if not d or d.get("available") is False:
            continue
        trend.append({
            "period_end": str(rr.period_end),
            "raw": d.get("raw"),
            "score": d.get("score"),
        })

    latest_rr = ratings[-1]
    latest_d = _ind(latest_rr) or {}
    available = bool(latest_d) and latest_d.get("available") is not False
    score = float(latest_d.get("score") or 0)
    raw = latest_d.get("raw")
    period_end: date = latest_rr.period_end

    # Peers: same period, deterministic model. Whole sector + same entity type.
    peer_rows = (
        db.query(RatingResult, Bank.bank_type)
        .join(Bank, Bank.id == RatingResult.bank_id)
        .filter(RatingResult.period_end == period_end,
                RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    sector_scores: List[float] = []
    type_scores: List[float] = []
    for rr, btype in peer_rows:
        d = (rr.indicator_details or {}).get(indicator_key)
        if not d or d.get("available") is False or d.get("score") is None:
            continue
        sc = float(d["score"])
        sector_scores.append(sc)
        if bank.bank_type is not None and btype == bank.bank_type:
            type_scores.append(sc)

    peers = None
    if available:
        peers = {
            "period_end": str(period_end),
            "sector": _peer_stats(sector_scores, score),
            "entity_type": _peer_stats(type_scores, score),
            "entity_type_label": bank.bank_type.value if bank.bank_type else None,
        }

    return {
        "bank_id": bank.id,
        "bank_name": bank.name,
        "indicator": indicator_key,
        "label": meta["label"],
        "sub_component": meta["sub"],
        "unit": meta["unit"],
        "direction": meta["direction"],
        "what_it_measures": meta["que"],
        "latest": {
            "period_end": str(period_end),
            "raw": raw,
            "score": round(score, 2),
            "available": available,
            "band": _band(score) if available else None,
        },
        "interpretation": _interpretation(meta, raw, score) if available else (
            f"{meta['label']}: sin dato disponible (N/D) en el último período. {meta['que']}"
        ),
        "trend": trend,
        "peers": peers,
    }


def ai_context(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the AI insight (bounded trend to keep tokens reasonable)."""
    return {
        "entidad": detail["bank_name"],
        "tipo_entidad": detail.get("peers", {}).get("entity_type_label") if detail.get("peers") else None,
        "periodo": detail["latest"]["period_end"],
        "indicador": detail["label"],
        "que_mide": detail["what_it_measures"],
        "direccion": detail["direction"],
        "unidad": detail["unit"],
        "valor_actual": detail["latest"]["raw"],
        "score": detail["latest"]["score"],
        "nivel": detail["latest"]["band"],
        "tendencia": detail["trend"][-12:],  # last ~3 years of quarters
        "pares": detail.get("peers"),
    }
