"""Market concentration of the EIF universe (system-level, not a per-bank input).

CR_n = Σ(metric of the n largest EIF) / Σ(metric of all EIF). Plus the system HHI
(Σ shareᵢ²). EIF = deposit-taking / credit institutions (bancos múltiples, AAyP,
bancos de ahorro y crédito, corporaciones de crédito) — excludes cambiarias (EIC) and
fiduciarias. This is a market-structure / competition metric for the Dashboard; it is
NOT the per-bank ``concentracion_top10`` (top-10 debtors), which the SIB doesn't publish.

Metric options (all from ``BankingData``): activos_totales (default) · depositos_totales
· cartera_bruta.
"""
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, BankingData, BankType

EIF_TYPES = (
    BankType.banca_multiple,
    BankType.aap,
    BankType.banco_ahorro_credito,
    BankType.corporacion_credito,
)

METRIC_FIELDS = {
    "activos": BankingData.activos_totales,
    "depositos": BankingData.depositos_totales,
    "cartera": BankingData.cartera_bruta,
}
METRIC_LABELS = {"activos": "Activos", "depositos": "Depósitos", "cartera": "Cartera bruta"}


def compute_market_concentration(
    db: Session, period_end: Optional[date] = None, metric: str = "activos",
) -> Dict[str, Any]:
    """CR5/CR10/HHI of the EIF universe for *metric* at *period_end* (latest if None)."""
    field = METRIC_FIELDS.get(metric)
    if field is None:
        raise ValueError(f"Métrica inválida: {metric}. Use activos|depositos|cartera.")

    if period_end is None:
        period_end = (
            db.query(func.max(BankingData.period_end))
            .join(Bank, Bank.id == BankingData.bank_id)
            .filter(Bank.bank_type.in_(EIF_TYPES), field.isnot(None), field > 0)
            .scalar()
        )
    if period_end is None:
        return {"period_end": None, "n_entities": 0, "metric": metric, "available": False}

    rows = (
        db.query(Bank.name, field)
        .join(BankingData, BankingData.bank_id == Bank.id)
        .filter(
            BankingData.period_end == period_end,
            Bank.bank_type.in_(EIF_TYPES),
            field.isnot(None),
            field > 0,
        )
        .all()
    )
    entities = sorted(((name, float(v)) for name, v in rows), key=lambda x: x[1], reverse=True)
    total = sum(v for _, v in entities)
    if not entities or total <= 0:
        return {"period_end": str(period_end), "n_entities": len(entities), "metric": metric, "available": False}

    def cr(n: int) -> float:
        return round(sum(v for _, v in entities[:n]) / total * 100, 2)

    hhi = round(sum((v / total) ** 2 for _, v in entities) * 10000, 1)  # 0..10000

    return {
        "period_end": str(period_end),
        "metric": metric,
        "metric_label": METRIC_LABELS[metric],
        "available": True,
        "n_entities": len(entities),
        "total": round(total, 2),
        # sujeto-ok: `metric_label` encabeza este mismo dict y nombra la población sobre la
        # que se computan los tres (activos o cartera bruta). Renombrar las claves rompería
        # el contrato con la UI y con `system_aggregate`, que las lee por nombre.
        "cr5": cr(5),
        "cr10": cr(10),   # sujeto-ok: ver `metric_label` arriba
        "hhi": hhi,       # sujeto-ok: ver `metric_label` arriba
        "top10": [
            # sujeto-ok: la fila trae `name`, así que el share está atribuido a SU entidad.
            {"name": name, "value": round(v, 2), "share": round(v / total * 100, 2)}
            for name, v in entities[:10]
        ],
    }
