"""Utilidad de los ÚLTIMOS 12 MESES (TTM) — la ventana con la que se miden ROA y ROE.

Por qué. El estado de resultados del SIB es ACUMULADO del ejercicio (Q1 = 3 meses, Q2 = 6…),
y el motor lo anualizaba multiplicando por ``12/mes``. Ese factor asume que cada trimestre
vale lo mismo, y el panel refuta el supuesto: sobre **71 banco-años de 16 bancos múltiples
(2021-2025)**, el primer trimestre concentra una mediana de **9,9%** de la utilidad anual,
mientras Q2, Q3 y Q4 aportan ~30% cada uno. El 97% de los casos tiene el Q1 bajo el 20%.

Consecuencia del supuesto falso: multiplicar por 4 un trimestre que vale 9,9% del año
proyecta una tasa anual del orden del 40% de la real. Verificado: BPD al Q1-2026 mostraba
ROE 10,2% contra 24,2% en el cierre — mismo banco, ningún cambio de negocio. Eso movía el
score (100 → 68) y daba vuelta la conclusión del informe.

La ventana móvil de 12 meses elimina la estacionalidad POR CONSTRUCCIÓN, sin depender de
calibrar ningún factor que haya que revisar cuando el patrón cambie:

    TTM(año Y, mes m) = acumulado(Y, m) + ejercicio_completo(Y-1) − acumulado(Y-1, m)

En un corte de DICIEMBRE el acumulado del ejercicio ya ES la ventana de 12 meses, así que
solo los cortes intermedios necesitan historia. Sin los tres insumos, ROA/ROE se declaran
NO DISPONIBLES (decisión del dueño): no se cae al método viejo, porque un número calculado
sobre un supuesto refutado es peor que un hueco declarado.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import BankingData

logger = logging.getLogger("sdq.banking.ttm")


def _ytd(db: Session, bank_id: str, period_end: date) -> Optional[float]:
    row = (db.query(BankingData)
           .filter(BankingData.bank_id == bank_id,
                   BankingData.period_end == period_end)
           .first())
    if row is None or row.utilidad_neta is None:
        return None
    return float(row.utilidad_neta)


def utilidad_ttm(db: Session, bank_id: str, period_end: date) -> Optional[float]:
    """Utilidad de los últimos 12 meses cerrados en *period_end*, o ``None``.

    ``None`` significa "no computable con la historia disponible" — el llamador debe
    declarar ROA/ROE no disponibles, nunca sustituirlos por el acumulado anualizado.
    """
    if period_end is None:
        return None
    actual = _ytd(db, bank_id, period_end)
    if actual is None:
        return None
    if period_end.month == 12:
        # Cierre de ejercicio: el acumulado YA cubre doce meses.
        return actual

    try:
        cierre_previo = date(period_end.year - 1, 12, 31)
        mismo_corte_previo = date(period_end.year - 1, period_end.month, period_end.day)
    except ValueError:  # 29-feb u otra fecha inexistente en el año previo
        return None

    fy_prev = _ytd(db, bank_id, cierre_previo)
    ytd_prev = _ytd(db, bank_id, mismo_corte_previo)
    if fy_prev is None or ytd_prev is None:
        logger.info("TTM no computable para %s en %s: falta %s", bank_id, period_end,
                    "cierre previo" if fy_prev is None else "mismo corte del año previo")
        return None
    return actual + fy_prev - ytd_prev


def attach_ttm(db: Session, record) -> None:
    """Adjunta ``utilidad_ttm`` al registro ANTES de puntuarlo.

    El motor de scoring es una función pura sin DB; la ventana móvil necesita historia, así
    que se resuelve acá y se pasa como un insumo más. Si no se puede, el atributo queda en
    ``None`` y el motor declara ROA/ROE no disponibles.
    """
    try:
        record.utilidad_ttm = utilidad_ttm(db, record.bank_id, record.period_end)
    except Exception as e:  # noqa: BLE001 — nunca tumba el scoring
        logger.warning("No se pudo adjuntar TTM (%s): ROA/ROE quedarán no disponibles.", e)
        record.utilidad_ttm = None
