"""El gate de admisión de una proyección: qué hace falta para que ancle algo.

Una proyección que no pasa este gate **no es una proyección mala: es un `GAP`**. Se degrada,
se declara, y su nota dice por qué — el motivo que devuelve esta función es el que alimenta
esa nota. Nunca se publica a medias.

Es el mismo movimiento que `shared/research/relevance.py::verify_rubric_relevance`, que ya
degrada RUBRIC→GAP cuando la rúbrica no aplica al sujeto.

**El valor de retorno es una TUPLA, y hay que desempaquetarla.** `(bool, str)`, y una tupla
no vacía es siempre truthy: quien la use como condición directa va a anclar TODA proyección,
con backtest o sin él — exactamente lo contrario de lo que este archivo existe para lograr.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Optional, Tuple

from shared.data.periodos import fin_del_periodo
from shared.registry.signals import ProjectionMeta

#: Mínimo de observaciones fuera de muestra para que un error diga algo. Doce es un piso
#: discutible y por eso está acá, a la vista: recalibrarlo es un PR a esta constante con la
#: justificación adentro, no una intuición repartida por el código.
MIN_OOS = 12

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _fecha(iso: str) -> Optional[date]:
    if not iso or not _ISO.fullmatch(str(iso).strip()):
        return None
    try:
        return date.fromisoformat(str(iso).strip())
    except ValueError:
        return None


def projection_is_admissible(meta: Optional[ProjectionMeta]) -> Tuple[bool, str]:
    """``(admisible, motivo)``. El motivo va vacío solo cuando admite.

    Rechaza cuando falta lo que haría juzgable el pronóstico, cuando los intervalos se
    contradicen entre sí o con el punto, cuando el backtest no alcanza para sostener el error
    que declara, o cuando el corte de información es posterior al período proyectado —que no
    es un pronóstico sino un ajuste con información que entonces no se tenía—.
    """
    if meta is None:
        return False, "no hay proyección declarada"

    for campo in ("model_id", "target_series", "backtest_id"):
        if not str(getattr(meta, campo, "") or "").strip():
            return False, f"falta {campo}: sin él la proyección no se puede rastrear"

    if not meta.intervals:
        return False, "sin intervalos: un punto sin incertidumbre no se publica"

    niveles = [lv for lv, _lo, _hi in meta.intervals]
    for lv in niveles:
        if not (0.0 < lv < 1.0):
            return False, f"nivel de intervalo {lv} fuera de (0, 1)"
    if len(set(niveles)) != len(niveles):
        return False, "hay un nivel de intervalo duplicado: dos anchos para la misma promesa"

    for lv, lo, hi in meta.intervals:
        if not (lo <= meta.point <= hi):
            return False, (f"el intervalo del {lv:.0%} no contiene al punto "
                           f"({lo} … {hi} vs {meta.point})")

    # Anidamiento: un nivel de confianza mayor tiene que contener al menor. Si el del 90% es
    # más angosto que el del 80%, uno de los dos está mal calculado y no se sabe cuál.
    ordenados = sorted(meta.intervals, key=lambda t: t[0])
    for (lv_a, lo_a, hi_a), (lv_b, lo_b, hi_b) in zip(ordenados, ordenados[1:]):
        if lo_b > lo_a or hi_b < hi_a:
            return False, (f"el intervalo del {lv_b:.0%} no está anidado sobre el del "
                           f"{lv_a:.0%}: uno de los dos está mal calculado")

    if meta.n_oos is None or meta.n_oos < MIN_OOS:
        return False, (f"{meta.n_oos} observaciones fuera de muestra: hacen falta al menos "
                       f"{MIN_OOS} para que el error diga algo")

    if meta.n_oos_overlapping is None:
        return False, ("no declara si las ventanas del backtest se solapan: el solapamiento "
                       "se declara, no se supone")

    if meta.oos_error is None or not math.isfinite(float(meta.oos_error)):
        return False, "el error fuera de muestra no es un número finito"

    corte = _fecha(meta.as_of)
    cierre = fin_del_periodo(meta.horizon)
    if corte is None:
        return False, "falta as_of: sin corte point-in-time no hay pronóstico que juzgar"
    # Un horizonte RELATIVO (`+4T`) no resuelve a un período absoluto: la condición no
    # aplica, y no aplicar no es fallar. Lo que no se puede verificar no se inventa.
    if cierre is not None and corte > cierre:
        return False, (f"el corte de información ({meta.as_of}) es posterior al cierre del "
                       f"período proyectado ({meta.horizon}): eso es un ajuste, no un "
                       "pronóstico")

    declarados = {lv for lv, _c, _n in meta.interval_coverage}
    sobrantes = declarados - set(niveles)
    if sobrantes:
        return False, ("la calibración declara niveles que no están entre los intervalos: "
                       f"{sorted(sobrantes)}")

    return True, ""
