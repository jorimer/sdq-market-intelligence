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
