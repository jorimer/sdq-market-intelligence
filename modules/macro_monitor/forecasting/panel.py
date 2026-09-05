"""El panel POINT-IN-TIME del nowcast: qué se sabía en cada fecha, no qué se sabe hoy.

Sin corte point-in-time un backtest se evalúa a sí mismo con información que en su momento no
existía, y el resultado es un track record inventado. Acá el corte es explícito: una
observación entra al panel de una fecha solo si **ya estaba publicada** en esa fecha.

El rezago de publicación se toma del mismo mapa que usa `tpm_modeling`
(`PUBLICATION_LAG_DAYS`), para que las dos capas del módulo cuenten la misma historia sobre
cuándo estuvo disponible cada cosa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.models.models import MacroSeries
from modules.macro_monitor.tpm_modeling.dataset import IMAE_INDEX_CODE, PUBLICATION_LAG_DAYS
from shared.data.periodos import fin_del_periodo

PIB_CODE = "bcrd.xls.pib_2018.serie_original_indice"

#: Cuánto tarda el BCRD en publicar el PIB trimestral tras cerrar el trimestre. El mapa de
#: `tpm_modeling` no lo tiene porque esa capa no usa el PIB; se declara acá y no se adivina en
#: cada llamada.
PIB_PUBLICATION_LAG_DAYS = 60

_LAG_IMAE = PUBLICATION_LAG_DAYS[IMAE_INDEX_CODE]

#: Nombre de la medida en que viaja un crecimiento. El sujeto viaja con el número: una tasa
#: sin su medida no se puede restar de otra, y restar una anual de una trimestral fue
#: exactamente lo que publicó ocho contracciones sectoriales que ningún modelo proyectó.
#: Ver `forecasting/tests/test_la_reconciliacion_resta_la_misma_medida.py`.
INTERANUAL = "interanual"
TRIMESTRAL = "trimestral"


def variacion_interanual_pct(serie: Dict[str, float], trimestres: Sequence[str]
                             ) -> Dict[str, float]:
    """Variación contra el MISMO trimestre del año anterior, en %.

    Vive acá, y no en cada capa, porque las dos que la necesitan —el bloque del BVAR y el
    panel sectorial— tienen que producir el MISMO número sobre el mismo índice para que la
    reconciliación sectorial signifique algo. Cuando cada una tenía la suya, una medía contra
    `t-1` y la otra contra `t-4`, y nada fallaba.

    Es la medida que la entrada canónica de `pib_real` declara citable —«el crecimiento (YoY
    del volumen) es invariante a la base»— y además la que no arrastra la estacionalidad: el
    índice del PIB que publica el BCRD es la serie ORIGINAL, cuyo QoQ va de −1,13 % (Q3) a
    +4,67 % (Q4) por puro calendario.
    """
    idx = {t: i for i, t in enumerate(trimestres)}
    out: Dict[str, float] = {}
    for t, i in idx.items():
        if i < 4:
            continue
        previo = serie.get(trimestres[i - 4])
        actual = serie.get(t)
        if previo and actual is not None and previo != 0:
            out[t] = (actual / previo - 1) * 100
    return out



def _publicado_el(period: str, lag_dias: int) -> Optional[date]:
    """Fecha en que una observación de ese período estuvo disponible."""
    cierre = fin_del_periodo(period)
    return None if cierre is None else cierre + timedelta(days=lag_dias)


def observaciones(db: Session, code: str) -> List[Tuple[str, float]]:
    """``[(período, valor)]`` de una serie, sin nulos, en orden cronológico."""
    filas = db.query(MacroSeries).filter_by(series_code=code).all()
    pares = [(str(f.period), float(f.value)) for f in filas if f.value is not None]
    return sorted(pares, key=lambda pv: (fin_del_periodo(pv[0]) or date.min, pv[0]))


def disponibles_al(pares: List[Tuple[str, float]], as_of: date,
                   lag_dias: int) -> List[Tuple[str, float]]:
    """Lo que estaba PUBLICADO al *as_of*. Es el corte que hace honesto un backtest."""
    return [(p, v) for p, v in pares
            if (_publicado_el(p, lag_dias) or date.max) <= as_of]


def trimestre_de(period_mensual: str) -> str:
    """``"2026-05"`` → ``"2026-Q2"``."""
    a, m = int(period_mensual[:4]), int(period_mensual[5:7])
    return f"{a}-Q{(m - 1) // 3 + 1}"


def meses_del_trimestre(pares: List[Tuple[str, float]], trimestre: str) -> List[float]:
    return [v for p, v in pares if len(p) == 7 and trimestre_de(p) == trimestre]


@dataclass(frozen=True)
class PanelTrimestral:
    """Lo que el nowcast necesita saber a una fecha: PIB e IMAE, ya agregados y alineados."""

    as_of: date
    #: ``{trimestre: Δlog}`` del PIB, solo trimestres con dato publicado al corte.
    dlog_pib: Dict[str, float]
    #: ``{trimestre: Δlog}`` del IMAE agregado, incluido el trimestre INCOMPLETO en curso.
    dlog_imae: Dict[str, float]
    #: Cuántos meses de IMAE tiene el trimestre que se está estimando (1, 2 o 3).
    meses_del_trimestre_objetivo: int
    trimestre_objetivo: Optional[str]


def _dlog(serie: List[Tuple[str, float]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for (_p0, v0), (p1, v1) in zip(serie, serie[1:]):
        if v0 > 0 and v1 > 0:
            out[p1] = math.log(v1) - math.log(v0)
    return out


def construir(db: Session, as_of: date, *, imputados: Optional[Dict[str, float]] = None
              ) -> PanelTrimestral:
    """El panel a una fecha. *imputados* completa los meses que faltan del trimestre en curso
    (los produce el paso 1 del nowcast); sin ellos, el trimestre incompleto se agrega con los
    meses que haya, que es lo correcto para la variante `m = 3`."""
    pib = disponibles_al(observaciones(db, PIB_CODE), as_of, PIB_PUBLICATION_LAG_DAYS)
    imae = disponibles_al(observaciones(db, IMAE_INDEX_CODE), as_of, _LAG_IMAE)
    if imputados:
        imae = sorted(list(imae) + list(imputados.items()),
                      key=lambda pv: (fin_del_periodo(pv[0]) or date.min, pv[0]))

    # IMAE agregado a trimestre: promedio simple de los meses disponibles de cada uno.
    por_trim: Dict[str, List[float]] = {}
    for p, v in imae:
        por_trim.setdefault(trimestre_de(p), []).append(v)
    imae_trim = sorted(((t, sum(vs) / len(vs)) for t, vs in por_trim.items()),
                       key=lambda tv: (fin_del_periodo(tv[0]) or date.min, tv[0]))

    ultimo_pib = pib[-1][0] if pib else None
    # El trimestre a estimar es el primero que el IMAE alcanza y el PIB todavía no publica.
    objetivo = next((t for t, _v in imae_trim
                     if ultimo_pib is None
                     or (fin_del_periodo(t) or date.min) > (fin_del_periodo(ultimo_pib) or date.min)),
                    None)
    m = len(por_trim.get(objetivo, [])) if objetivo else 0
    return PanelTrimestral(as_of=as_of, dlog_pib=_dlog(pib), dlog_imae=_dlog(imae_trim),
                           meses_del_trimestre_objetivo=m, trimestre_objetivo=objetivo)
