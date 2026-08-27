"""Agregado de sistema anonimizado para el nivel Pulse (hueco G1 de Banca).

Pulse es de granularidad *system*: NUNCA emite el rating de un banco. Este módulo
agrupa los ratings deterministas de todas las entidades de un período en **4 bandas**
(decisión de doctrina, 2026-06-23) y devuelve la distribución + estadísticas del
sistema, sin identificadores. El roster de nombres se devuelve por separado para que
el sensor de anonimización del framework verifique que no se filtró ninguno al payload.

Bandas (sobre el score 0–100, alineadas a la escala de 10 tiers):
    Fuerte     ≥ 80     (SDQ-AAA · AA+ · AA · AA-)
    Adecuado   65–79.99 (SDQ-A+ · A · A-)
    Vigilancia 45–64.99 (SDQ-BBB+ · BBB)
    Crítico    < 45     (SDQ-D)
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.scoring.market_concentration import compute_market_concentration
from shared.narrative.derived import derived_figures

# (nombre de banda, umbral inferior inclusivo de score). Orden descendente.
PULSE_BANDS: List[Tuple[str, float]] = [
    ("Fuerte", 80.0),
    ("Adecuado", 65.0),
    ("Vigilancia", 45.0),
    ("Crítico", 0.0),
]
BAND_NAMES: Tuple[str, ...] = tuple(name for name, _ in PULSE_BANDS)


def band_for_score(score: float) -> str:
    """Banda de anonimización para un score [0,100]."""
    for name, lower in PULSE_BANDS:
        if score >= lower:
            return name
    return PULSE_BANDS[-1][0]


def system_band_distribution(
    db: Session, period_end: Optional[date] = None,
) -> Dict[str, Any]:
    """Distribución del sistema por banda en *period_end* (último si None).

    Devuelve siempre las 4 bandas (conteo 0 si vacías) + n_entities + score promedio
    del sistema + ``roster`` (nombres, SOLO para el sensor de anonimización — no van al
    payload narrado). Lee SOLO ratings deterministas (la fuente canónica).
    """
    if period_end is None:
        period_end = (
            db.query(func.max(RatingResult.period_end))
            .filter(RatingResult.model_type == ModelType.deterministic)
            .scalar()
        )
    if period_end is None:
        return {"available": False, "period": None, "n_entities": 0,
                "band_distribution": {name: 0 for name in BAND_NAMES},
                "system_avg_score": None, "roster": []}

    rows = (
        db.query(Bank.name, RatingResult.overall_score)
        .join(RatingResult, RatingResult.bank_id == Bank.id)
        .filter(RatingResult.period_end == period_end,
                RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    distribution: Dict[str, int] = {name: 0 for name in BAND_NAMES}
    roster: List[str] = []
    total = 0.0
    for name, score in rows:
        s = float(score)
        distribution[band_for_score(s)] += 1
        total += s
        if name:
            roster.append(name)

    n = len(rows)
    return {
        "available": n > 0,
        "period": str(period_end),
        "n_entities": n,
        "band_distribution": distribution,
        "system_avg_score": round(total / n, 2) if n else None,
        "roster": roster,
    }


# Umbral de score (puntos) para llamar a una variación del promedio una tendencia y no ruido.
_TREND_EPS = 0.5


def _prior_det_period(db: Session, period_end: date) -> Optional[date]:
    """Período determinista inmediatamente anterior a *period_end* (None si es el primero)."""
    return (
        db.query(func.max(RatingResult.period_end))
        .filter(RatingResult.model_type == ModelType.deterministic,
                RatingResult.period_end < period_end)
        .scalar()
    )


def _band_shares(distribution: Dict[str, int], n: int) -> Dict[str, float]:
    """Share (%) de cada banda sobre el total. Se sirve precalculado para que la narrativa
    lo COPIE (el modelo erra al dividir conteos)."""
    return {name: round(distribution.get(name, 0) / n * 100, 1) for name in BAND_NAMES}


def system_pulse_aggregate(
    db: Session, period_end: Optional[date] = None,
) -> Dict[str, Any]:
    """Agregado Pulse ENRIQUECIDO con cifras derivadas de SISTEMA (anonimizadas).

    Extiende ``system_band_distribution`` con lo que la narrativa de sistema necesita para
    anclar una lectura —en vez de enumerar lo que le falta—, todo sin identificadores:

      - ``cifras_derivadas``: share por banda, núcleo sólido (Fuerte+Adecuado), cola de
        riesgo (Vigilancia+Crítico), concentración de activos (CR5/CR10/HHI) y la variación
        del score promedio vs. el período previo (vía ``derived_figures``).
      - ``tendencia_score``: nivel actual vs. previo del promedio del sistema y su dirección
        (asciende / desciende / estable), para distinguir techo de piso en ascenso.

    Devuelve siempre ``roster`` aparte (solo para el sensor de anonimización, nunca narrado).
    Si no hay datos, replica el contrato vacío de ``system_band_distribution`` (sin enriquecer).
    """
    base = system_band_distribution(db, period_end)
    if not base["available"]:
        return base

    n = base["n_entities"]
    dist = base["band_distribution"]
    avg = base["system_avg_score"]
    resolved = date.fromisoformat(base["period"])

    shares = _band_shares(dist, n)
    nucleo = round((dist.get("Fuerte", 0) + dist.get("Adecuado", 0)) / n * 100, 1)
    cola = round((dist.get("Vigilancia", 0) + dist.get("Crítico", 0)) / n * 100, 1)

    cifras: Dict[str, Any] = {
        # sujeto-ok: la clave nombra su población —el reparto POR BANDA del sistema— y el
        # valor es un dict banda→porcentaje, no una cifra suelta que se pueda reatribuir.
        "share_por_banda_pct": shares,
        "nucleo_solido_pct": nucleo,      # Fuerte + Adecuado
        "cola_de_riesgo_pct": cola,       # Vigilancia + Crítico
    }

    # Concentración de activos (estructura del sistema). Solo cifras agregadas — NUNCA el
    # top10 nominal que devuelve el cálculo (filtraría identificadores). OJO: el universo de
    # concentración son las EIF con activos > 0, no necesariamente las mismas entidades que
    # la distribución de bandas (todos los ratings deterministas) — por eso se sirve como
    # bloque de "estructura" aparte, no como un % sobre n_entities.
    conc = compute_market_concentration(db, resolved, "activos")
    if conc.get("available"):
        cifras["concentracion_activos"] = {
            # sujeto-ok: `metric_label` va primero y nombra la población; además el bloque
            # entero cuelga de `concentracion_activos`, que ya la declara.
            "metric_label": conc["metric_label"], "cr5": conc["cr5"],
            # sujeto-ok: ambos cuelgan de `concentracion_activos`, que nombra la población
            "cr10": conc["cr10"], "hhi": conc["hhi"],
        }

    # Trayectoria vs. período previo (aceleración: techo estabilizado vs. piso en ascenso).
    tendencia: Optional[Dict[str, Any]] = None
    prior = _prior_det_period(db, resolved)
    if prior is not None and avg is not None:
        prev = system_band_distribution(db, prior)
        prev_avg = prev["system_avg_score"]
        if prev["available"] and prev_avg is not None:
            delta = round(avg - prev_avg, 2)
            direccion = ("asciende" if delta > _TREND_EPS
                         else "desciende" if delta < -_TREND_EPS else "estable")
            tendencia = {
                "periodo_actual": base["period"], "periodo_previo": prev["period"],
                "score_actual": avg, "score_previo": prev_avg,
                "delta_pts": delta, "direccion": direccion,
            }
            # Forma canónica que el numeric_guard ya entiende (variacion_score_actual).
            trend = [{"periodo": prev["period"], "score": prev_avg},
                     {"periodo": base["period"], "score": avg}]
            cifras.update(derived_figures(score=avg, subcomponents=[], trend=trend))

    base["cifras_derivadas"] = cifras
    base["tendencia_score"] = tendencia
    return base
