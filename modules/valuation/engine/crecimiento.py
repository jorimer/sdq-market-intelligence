"""El techo del crecimiento terminal: una entidad no puede crecer más que su economía.

**El defecto que esto cierra, medido en producción.** Valuando el BHD con el cierre de 2025
el modelo devolvía un P/B implícito de **1,40× a 12,23×**. El panel de ocho transacciones de
esta misma plataforma dice que lo que se paga por un banco del Caribe es **0,77× a 2,73×**.
Un 12,23× no es un valor alto: es un modelo roto.

La causa es aritmética. Con `g = b × ROE` y un ROE de 22,57 %, la retención medida de la
banca múltiple (0,75) da `g = 16,9 %`; contra un `Ke` de 14,28 % la perpetuidad ni siquiera
converge, y con la retención vieja del 0,60 daba `g = 13,54 %`, que converge por 0,74 pp y
hace explotar el terminal.

**El guard que ya existía no alcanza.** `_exigir_convergencia` atrapa `g >= Ke`, o sea el
caso que NO converge. No atrapa el que converge y es imposible — y ése es peor, porque
devuelve un número.

**El techo.** El PIB nominal dominicano crece **~9 %** de largo plazo. Una entidad que crece
13,5 % para siempre termina siendo más grande que la economía que la contiene, lo cual no es
una valuación agresiva sino una imposibilidad. El techo se COMPUTA de nuestra propia serie
de PIB nominal y no se escribe a mano, porque una constante copiada envejece sin avisar.

**Y cuando el techo muerde, se DECLARA.** Es un supuesto que cambia el valor: pasar de
`g = 13,54 %` a `g = 9,03 %` lleva el extremo favorable de 12,23× a 2,89×. Un cambio de ese
tamaño no puede viajar callado.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.valuation.crecimiento")

#: Variación interanual del PIB NOMINAL. Nominal y no real a propósito: `g` compite contra un
#: `Ke` nominal en pesos, y mezclar una tasa real con una nominal descuenta mal por toda la
#: inflación esperada.
SERIE_PIB_NOMINAL = "bcrd.xls.pib_deflactor_2018.pib_nominal_millones_de_rd_variacion_interanual"

#: Techo de respaldo, en %. Se usa SOLO si la serie no está disponible, y su uso se declara.
#: Es la mediana medida el 2026-09-05 sobre 29 trimestres.
TECHO_DE_RESPALDO = 9.03

#: Cuántas observaciones hacen falta para que la mediana signifique algo. Con menos, el techo
#: quedaría a merced de un par de trimestres.
MINIMO_DE_OBSERVACIONES = 12


@dataclass(frozen=True)
class TechoDeCrecimiento:
    """El techo, de dónde salió, y si es medido o de respaldo."""

    valor_pct: float
    n_observaciones: int
    es_medido: bool
    evidencia: str


def techo_nominal(db: Session, *, serie: str = SERIE_PIB_NOMINAL) -> TechoDeCrecimiento:
    """La mediana de la variación interanual del PIB nominal.

    Mediana y no media: la serie trae la caída de 2020 y el rebote de 2021, y una media los
    arrastra a los dos. La mediana de la serie larga es lo que una perpetuidad necesita.
    """
    from modules.macro_monitor.forecasting.panel import observaciones

    try:
        vals: List[float] = [float(v) for _p, v in observaciones(db, serie) if v is not None]
    except Exception as e:  # noqa: BLE001 — un techo que falla no puede costar la valuación
        logger.warning("no se pudo medir el techo de crecimiento: %s", e)
        vals = []
    if len(vals) < MINIMO_DE_OBSERVACIONES:
        return TechoDeCrecimiento(
            TECHO_DE_RESPALDO, len(vals), False,
            f"TECHO DE RESPALDO ({TECHO_DE_RESPALDO} %): la serie de PIB nominal tiene "
            f"{len(vals)} observación(es) y hacen falta {MINIMO_DE_OBSERVACIONES}. Es la "
            "mediana medida el 2026-09-05 sobre 29 trimestres, y se declara como respaldo "
            "porque una constante copiada envejece sin avisar.")
    m = statistics.median(vals)
    return TechoDeCrecimiento(
        round(m, 4), len(vals), True,
        f"Mediana de la variación interanual del PIB nominal sobre {len(vals)} trimestres. "
        "Mediana y no media: la serie trae la caída de 2020 y el rebote de 2021, y una media "
        "los arrastra a los dos.")


def g_terminal(roe_pct: float, retencion: float,
               techo: TechoDeCrecimiento) -> Tuple[float, Optional[str]]:
    """`min(b × ROE, techo)`, y el aviso cuando el techo muerde.

    Devuelve `(g, aviso)`. El aviso es `None` cuando el crecimiento sostenible ya estaba por
    debajo del techo — que es el caso normal de una entidad con ROE moderado, y no hay nada
    que declarar.
    """
    sostenible = retencion * roe_pct
    if sostenible <= techo.valor_pct:
        return round(sostenible, 4), None
    return round(techo.valor_pct, 4), (
        f"El crecimiento sostenible de esta entidad —retención {retencion:.2f} × ROE "
        f"{roe_pct:.2f} % = {sostenible:.2f} %— supera el crecimiento nominal de la economía "
        f"({techo.valor_pct:.2f} %), así que el terminal se computa con el techo. Crecer por "
        "encima de la economía para SIEMPRE es una imposibilidad, no una valuación agresiva: "
        "la entidad terminaría siendo más grande que el país. El supuesto se declara porque "
        "cambia el valor, y mucho.")
