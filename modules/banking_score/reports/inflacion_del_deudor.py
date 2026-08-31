"""La inflación que enfrenta el DEUDOR, no la del titular.

Por qué existe. La inflación que publica el titular es un promedio de la economía. La que
aprieta a un hogar endeudado es la de SU canasta, y el BCRD la publica abierta por quintil de
ingreso — una planilla que estuvo veintiocho meses sin ingerir. Importa acá porque el crédito
de consumo es el rubro más grande del sistema (26,6% del crédito al cierre de marzo de 2026) y
vive en los quintiles bajos: es la variable de capacidad de pago que faltaba para explicar por
qué se deteriora esa cartera.

Qué hace que esto no lo pueda producir un banco. Los datos del BCRD son públicos: cualquiera
los baja. Lo que no puede hacer un banco es CRUZARLOS con la composición sectorial del libro
de las noventa y una entidades restantes — decir «tu consumo es el 41,6% de tu cartera y su
mora corre 2,7 puntos sobre la del resto del sistema, en un período en que la canasta del
quintil 1 subió 7 puntos más que la del quintil 5». La inflación por quintil sola es un dato
público; junto al mapa sectorial es una atribución.

Doctrina aplicada. La brecha entre quintiles se COMPUTA acá y el modelo la copia. La serie es
un ÍNDICE (base 2019-2020), así que la acumulación se calcula sobre índices y nunca sumando
variaciones. Y si falta un quintil, no se rellena: se devuelve `None` y la sección no lo
menciona — media brecha es peor que ninguna, porque parece una medición.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: Las cinco series de ÍNDICE del IPC por quintil de ingreso (BCRD, base 2019-2020).
#: Son índices y no tasas a propósito: la planilla trae además cinco columnas de tasa que la
#: inferencia nombra por COORDENADA (`..._c5`, `..._c7`) sin decir de qué quintil son, y una
#: tasa que no nombra su población es exactamente lo que no se debe servir. La variación se
#: deriva del índice, que sí viaja con su sujeto en la clave.
_PREFIJO = "bcrd.xls.ipc_quintiles_base_2019_2020.quintil_"
QUINTILES: Tuple[int, ...] = (1, 2, 3, 4, 5)

#: Mínimo de meses para afirmar una acumulación. Con menos, la «brecha» es ruido de dos
#: lecturas y no una trayectoria.
_MIN_MESES = 12


def _serie(db: Session, quintil: int, hasta: str) -> List[Tuple[str, float]]:
    """Los puntos (período, índice) del quintil, hasta *hasta* inclusive.

    El corte es el del INFORME: una serie que llegue a julio no puede aparecer en un informe
    de marzo, que es el mismo motivo por el que el telón macro se poda por fecha."""
    from modules.macro_monitor.models.models import MacroSeries

    filas = (db.query(MacroSeries.period, MacroSeries.value)
             .filter(MacroSeries.series_code == f"{_PREFIJO}{quintil}",
                     MacroSeries.value.isnot(None),
                     MacroSeries.period <= hasta)
             .order_by(MacroSeries.period)
             .all())
    return [(str(p), float(v)) for p, v in filas]


def _acumulada(puntos: List[Tuple[str, float]]) -> Optional[float]:
    """Variación acumulada del ÍNDICE entre el primer y el último punto, en %.

    Sobre índices, nunca sumando variaciones mensuales: sumar tasas subestima la
    acumulación por el interés compuesto que ignora, y sobre cinco años la diferencia deja
    de ser cosmética."""
    if len(puntos) < _MIN_MESES:
        return None
    base = puntos[0][1]
    if base <= 0:
        return None
    return round((puntos[-1][1] / base - 1.0) * 100.0, 2)


def inflacion_por_quintil(db: Session, corte: date) -> Optional[Dict[str, Any]]:
    """La inflación acumulada por quintil de ingreso hasta *corte*, con su brecha.

    Devuelve ``None`` cuando falta algún quintil: la lectura es la COMPARACIÓN entre el
    primero y el quinto, y con cuatro de cinco no se puede afirmar que el primero sea el
    extremo. Declarar la brecha es mejor que publicar media."""
    hasta = f"{corte.year}-{corte.month:02d}"
    series = {q: _serie(db, q, hasta) for q in QUINTILES}
    medidos = {q: _acumulada(p) for q, p in series.items()}
    faltan = [q for q, v in medidos.items() if v is None]
    if faltan:
        logger.info("Inflación por quintil omitida hasta %s: sin serie suficiente en %s",
                    hasta, faltan)
        return None
    # Estrechado UNA vez, acá: pasado este punto no hay huecos, y cada lectura de abajo no
    # tiene que volver a defenderse de un `None` que ya se descartó.
    acum: Dict[int, float] = {q: v for q, v in medidos.items() if v is not None}

    primero, ultimo = series[1][0][0], series[1][-1][0]
    q1, q5 = acum[1], acum[5]
    return {
        "desde": primero,
        "hasta": ultimo,
        "meses": len(series[1]),
        # El SUJETO en la clave: es la inflación acumulada de la canasta de CADA quintil de
        # ingreso, no la del índice general ni la de un sector.
        "inflacion_acumulada_por_quintil_de_ingreso_pct": {
            f"quintil_{q}": v for q, v in acum.items()},
        # LA RELACIÓN SE COMPUTA ACÁ. El modelo la copia; derivarla de dos porcentajes es
        # cómo se invierte una dirección.
        "brecha_quintil_1_menos_quintil_5_pp": round(q1 - q5, 2),
        "quintil_mas_golpeado": f"quintil_{max(acum, key=lambda q: acum[q])}",
        "que_es": ("inflación acumulada de la canasta de cada quintil de ingreso, medida "
                   "sobre el índice del BCRD (base 2019-2020) entre los dos extremos de la "
                   "ventana; una brecha positiva significa que la canasta del quintil más "
                   "pobre subió MÁS que la del más rico"),
        "por_que_importa_en_credito": (
            "el crédito de consumo se concentra en los quintiles de menor ingreso, así que "
            "su capacidad de pago la fija esta inflación y no la del índice general"),
    }
