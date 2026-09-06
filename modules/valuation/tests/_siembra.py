"""Siembra de entidades para los tests del eje, con CORTES TRIMESTRALES.

Todas las fixtures del eje sembraban solo cierres de diciembre, donde la utilidad acumulada
del ejercicio YA es la de doce meses. Ahí el defecto de `historia_de` —dividir el acumulado
de 3, 6 o 9 meses por el patrimonio del trimestre anterior— no existe, y catorce archivos de
tests pasaban en verde con un ROE proyectado que en producción salía a ~60 % del real.

La forma sembrada es la que publica la SIB: `utilidad_neta` ACUMULADA del ejercicio, con la
estacionalidad medida en `banking_score/scoring/ttm.py` (el primer trimestre concentra ~10 %
de la utilidad anual; los otros tres, ~30 % cada uno).
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

#: Fracción del ejercicio acumulada a cada corte — la estacionalidad medida, no una uniforme.
FRACCION_YTD = {3: 0.10, 6: 0.40, 9: 0.70, 12: 1.00}
CORTES = ((3, 31), (6, 30), (9, 30), (12, 31))


def sembrar_trimestres(db, bank_id: str, *, patrimonio_diciembre: Sequence[float],
                       anios: Sequence[int], roe_anual_pct: float = 10.0,
                       sin_utilidad_en: Optional[Sequence[date]] = None) -> None:
    """Cuatro cortes por año. `patrimonio_diciembre[i]` es el cierre de `anios[i]`; los cortes
    intermedios interpolan geométricamente. La utilidad del año es `roe_anual_pct` sobre el
    patrimonio de APERTURA (el diciembre anterior) y se acumula por `FRACCION_YTD`. El primer
    año no tiene apertura: se siembra con utilidad acumulada sobre su propio cierre."""
    from modules.banking_score.models.models import BankingData, DataSource
    omitir = set(sin_utilidad_en or ())
    for i, (anio, p_dic) in enumerate(zip(anios, patrimonio_diciembre)):
        p_prev = patrimonio_diciembre[i - 1] if i else p_dic
        util_anual = p_prev * roe_anual_pct / 100.0
        for q, (m, d) in enumerate(CORTES, start=1):
            corte = date(anio, m, d)
            patr = p_prev * (p_dic / p_prev) ** (q / 4.0)
            util = None if corte in omitir else util_anual * FRACCION_YTD[m]
            db.add(BankingData(bank_id=bank_id, period_end=corte, patrimonio_tecnico=patr,
                               utilidad_neta=util, source=DataSource.sib_api))
