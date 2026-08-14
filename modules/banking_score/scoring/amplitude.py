"""Amplitud del deep dive de banca (Fase 4): trayectoria multi-período y percentil
vs el sistema, por indicador.

Ambas funciones son deterministas (sin IA) y leen la misma fuente que ya alimenta
los drill-downs (``RatingResult`` + ``RatingResult.indicator_details``). Se calculan
en la capa que tiene ``db`` (``BankingProduct.snapshot``) y viajan dentro del
``scoring_result`` del snapshot, porque ``narratives``/``render`` operan sin DB.

- ``entity_trajectories``: para UNA entidad, la serie cronológica (últimos *n*
  trimestres) del score global, de cada sub-componente y de cada indicador. Un solo
  query del historial de la entidad (no 19 llamadas a ``build_indicator_detail``).
- ``period_percentiles``: para un período, el percentil de la entidad vs el sistema
  (sector completo + mismo tipo de entidad) en el score global, cada sub-componente
  y cada indicador. Un solo query de todos los ``RatingResult`` del período.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.scoring.indicator_detail import _percentile, _quantile

# Sub-componentes → columna de score en RatingResult (para la trayectoria por dimensión).
_SUB_SCORE_ATTR: Dict[str, str] = {
    "solidez": "solidez_score",
    "calidad": "calidad_score",
    "eficiencia": "eficiencia_score",
    "liquidez": "liquidez_score",
    "diversificacion": "diversificacion_score",
}


# Ventana de la trayectoria: cuántos cortes ve la narrativa Y cuántos imprime la tabla.
# Es UNA constante a propósito. Cuando eran dos números independientes (contexto 8, tabla 6)
# el informe citó en prosa dos anclas —el pico de junio-24 y el inicio de ventana de
# marzo-24— que no estaban impresas: ambas correctas y ninguna verificable por el lector.
TRAJECTORY_WINDOW = 8


def entity_trajectories(db: Session, bank: Bank, n: int = TRAJECTORY_WINDOW,
                        as_of: Optional[date] = None) -> Dict[str, Any]:
    """Serie cronológica (ascendente, últimos *n* trimestres) del score global, de
    cada sub-componente y de cada indicador para *bank*.

    Un solo query del historial determinista. Los indicadores salen del JSON
    ``indicator_details``; se omiten los períodos donde el indicador es N/D, de modo
    que la serie de cada indicador solo contiene puntos medidos.

    ``as_of`` recorta la serie a ese corte (inclusive). Un informe se emite AL CORTE, así
    que su trayectoria no debe contener períodos posteriores al que anuncia la portada.

    Shape::

        {
          "n_periods": int,
          "overall": [{"period_end": str, "score": float, "tier": str}, ...],
          "sub": {"solidez": [{"period_end": str, "score": float}, ...], ...},
          "indicators": {"solvencia": [{"period_end": str, "raw": float,
                                        "score": float}, ...], ...},
        }
    """
    q = db.query(RatingResult).filter(
        RatingResult.bank_id == bank.id,
        RatingResult.model_type == ModelType.deterministic,
    )
    # Recorte al CORTE del informe. Sin esto la serie arrastraba períodos POSTERIORES al
    # que anuncia la portada: un informe "al 31-dic-2025" mostraba el rating real de
    # marzo-2026, y la narrativa —que no tiene forma de saber qué es ese número— lo
    # racionalizó inventando etiquetas, distintas en cada sección ("proyectado" en
    # Eficiencia, "preliminar" en Solidez, "trayectoria histórica y proyectada" en
    # Liquidez). La palabra "proyectado" no existe en el código: el motor no proyecta nada.
    # El informe es un documento AL CORTE — su score, sus percentiles y sus indicadores ya
    # lo son; la trayectoria debe serlo también.
    if as_of is not None:
        q = q.filter(RatingResult.period_end <= as_of)
    ratings = q.order_by(RatingResult.period_end.asc()).all()
    if not ratings:
        return {"n_periods": 0, "overall": [], "sub": {}, "indicators": {}}

    ratings = ratings[-n:] if n and len(ratings) > n else ratings

    overall: List[Dict[str, Any]] = []
    sub: Dict[str, List[Dict[str, Any]]] = {k: [] for k in _SUB_SCORE_ATTR}
    indicators: Dict[str, List[Dict[str, Any]]] = {}

    for rr in ratings:
        pe = str(rr.period_end)
        if rr.overall_score is not None:
            overall.append({"period_end": pe, "score": round(float(rr.overall_score), 2),
                            "banda_resiliencia": rr.banda_resiliencia})
        for sk, attr in _SUB_SCORE_ATTR.items():
            val = getattr(rr, attr, None)
            if val is not None:
                sub[sk].append({"period_end": pe, "score": round(float(val), 2)})
        for key, d in (rr.indicator_details or {}).items():
            if not isinstance(d, dict) or d.get("available") is False or d.get("score") is None:
                continue
            indicators.setdefault(key, []).append({
                "period_end": pe, "raw": d.get("raw"), "score": round(float(d["score"]), 2),
            })

    return {
        "n_periods": len(ratings),
        "overall": overall,
        "sub": {k: v for k, v in sub.items() if v},
        "indicators": indicators,
    }


def _stats(scores: List[float], value: float) -> Optional[Dict[str, Any]]:
    """Percentil + distribución de *value* dentro de *scores*. None si no hay pares."""
    vals = sorted(s for s in scores if s is not None)
    if not vals:
        return None
    return {
        "n": len(vals),
        "percentile": _percentile(vals, value),
        "median_score": _quantile(vals, 0.5),
        "p25_score": _quantile(vals, 0.25),
        "p75_score": _quantile(vals, 0.75),
    }


def period_percentiles(db: Session, bank: Bank, period_end: date) -> Dict[str, Any]:
    """Percentil de *bank* vs el sistema en *period_end*: score global, cada
    sub-componente y cada indicador. Sector completo + mismo tipo de entidad.

    Un solo query de todos los ``RatingResult`` del período. Shape::

        {
          "period_end": str,
          "entity_type_label": str | None,
          "overall": {"sector": {...}, "entity_type": {...}} | None,
          "sub": {"solidez": {"sector": {...}, "entity_type": {...}}, ...},
          "indicators": {"solvencia": {"sector": {...}, "entity_type": {...}}, ...},
        }

    Cada bloque ``sector``/``entity_type`` es el dict de :func:`_stats` (percentile,
    n, mediana, p25, p75) o None si no hay pares medibles.
    """
    rows = (
        db.query(RatingResult, Bank.bank_type)
        .join(Bank, Bank.id == RatingResult.bank_id)
        .filter(RatingResult.period_end == period_end,
                RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    btype = bank.bank_type

    # Acumula scores por eje (overall, sub, indicador), separando sector vs tipo.
    overall_sector: List[float] = []
    overall_type: List[float] = []
    sub_sector: Dict[str, List[float]] = {k: [] for k in _SUB_SCORE_ATTR}
    sub_type: Dict[str, List[float]] = {k: [] for k in _SUB_SCORE_ATTR}
    ind_sector: Dict[str, List[float]] = {}
    ind_type: Dict[str, List[float]] = {}

    own_overall: Optional[float] = None
    own_sub: Dict[str, float] = {}
    own_ind: Dict[str, float] = {}

    for rr, rr_type in rows:
        is_self = rr.bank_id == bank.id
        same_type = btype is not None and rr_type == btype
        if rr.overall_score is not None:
            sc = float(rr.overall_score)
            overall_sector.append(sc)
            if same_type:
                overall_type.append(sc)
            if is_self:
                own_overall = sc
        for sk, attr in _SUB_SCORE_ATTR.items():
            val = getattr(rr, attr, None)
            if val is None:
                continue
            sc = float(val)
            sub_sector[sk].append(sc)
            if same_type:
                sub_type[sk].append(sc)
            if is_self:
                own_sub[sk] = sc
        for key, d in (rr.indicator_details or {}).items():
            if not isinstance(d, dict) or d.get("available") is False or d.get("score") is None:
                continue
            sc = float(d["score"])
            ind_sector.setdefault(key, []).append(sc)
            if same_type:
                ind_type.setdefault(key, []).append(sc)
            if is_self:
                own_ind[key] = sc

    def _pair(sector_scores: List[float], type_scores: List[float],
              own: Optional[float]) -> Optional[Dict[str, Any]]:
        if own is None:
            return None
        block: Dict[str, Any] = {"sector": _stats(sector_scores, own)}
        if btype is not None:
            block["entity_type"] = _stats(type_scores, own)
        return block

    sub_out = {sk: _pair(sub_sector[sk], sub_type[sk], own_sub.get(sk))
               for sk in _SUB_SCORE_ATTR if own_sub.get(sk) is not None}
    ind_out = {k: _pair(ind_sector.get(k, []), ind_type.get(k, []), own_ind[k])
               for k in own_ind}

    return {
        "period_end": str(period_end),
        "entity_type_label": btype.value if btype is not None else None,
        "overall": _pair(overall_sector, overall_type, own_overall),
        "sub": sub_out,
        "indicators": {k: v for k, v in ind_out.items() if v is not None},
    }
