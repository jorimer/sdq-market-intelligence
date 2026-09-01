"""El presupuesto de ensamblado, VISIBLE desde el motor de narrativa.

**El problema.** El techo de tiempo de un informe (`PRESUPUESTO_DE_ENSAMBLADO_S`) vive en el
ensamblador y el motor no lo conoce. Cuando el guard numérico marca una cifra, el motor
regenera hasta dos veces sin saber cuánto queda: una regeneración puede arrancar a los 250 s
de un presupuesto de 270 y garantizar el corte. Y el corte **destruye el ensamblado entero**
—las otras secciones ya generadas se descartan y el reintento del usuario arranca de cero—,
mientras que no regenerar habría entregado el informe con su marca.

El intercambio, dicho de frente: **se cambia una sección posiblemente mejorada por un informe
entregado.** Y ni siquiera es tan caro como suena, porque la regla vigente de dos capas solo
bloquea la entrega cuando el JUEZ confirma la marca; en la ventana medida del 2026-09-01 las
diez marcas registradas eran del detector mecánico y ninguna bloqueó nada. Es decir: hoy se
gastan hasta dos llamadas, y a veces el informe entero, sobre marcas que se iban a publicar.

**Sin presupuesto declarado no bloquea NADA.** Los tests, los scripts y los trabajos de fondo
se comportan igual que antes. La ausencia de presupuesto es «no hay techo», nunca «no queda
tiempo» — invertir ese default convertiría un módulo de observación en un estrangulador.

**`None` y no `0.0` para «sin presupuesto».** `time.monotonic()` no tiene origen fijo, así que
un centinela numérico ata la lógica al *uptime* del proceso: en un servidor recién arrancado
0.0 es «ahora» y en uno de tres días es un instante muy pasado. Ese defecto ya se pagó en este
repo.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
from typing import Iterator, Optional

#: Instante monótono en que vence el presupuesto. `None` = no hay techo declarado.
_vence_en: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "vencimiento_del_ensamblado", default=None)

#: Margen sobre el costo estimado de una regeneración. Terminar EXACTO en el vencimiento no
#: sirve de nada —el ensamblado se corta igual—, y la estimación es una sola observación.
MARGEN = 1.2


@contextlib.contextmanager
def con_presupuesto(segundos: Optional[float]) -> Iterator[None]:
    """Declara cuánto tiempo tiene el ensamblado, para todo lo que corra adentro.

    **Anidar solo puede ACHICAR.** Si ya hay un vencimiento y el nuevo es posterior, se
    conserva el que estaba: un presupuesto interno no puede extender el del ensamblado que
    lo contiene, porque el que corta es el de afuera.
    """
    if segundos is None or segundos <= 0:
        yield
        return
    nuevo = time.monotonic() + float(segundos)
    actual = _vence_en.get()
    token = _vence_en.set(nuevo if actual is None else min(actual, nuevo))
    try:
        yield
    finally:
        _vence_en.reset(token)


def queda() -> Optional[float]:
    """Segundos que faltan para el vencimiento; ``None`` si no hay presupuesto declarado.

    Puede ser NEGATIVO: el presupuesto ya venció y el ensamblado está por cortarse. Se
    devuelve tal cual en vez de acotarlo a cero — «se pasó por 12 s» y «llegó justo» son
    cosas distintas, y quien lo registre necesita distinguirlas.
    """
    vence = _vence_en.get()
    return None if vence is None else vence - time.monotonic()


def cabe(costo_estimado_s: Optional[float]) -> bool:
    """¿Entra en lo que queda un trabajo que cuesta *costo_estimado_s*?

    Sin presupuesto declarado, siempre entra. Sin estimación tampoco se bloquea: no saber
    cuánto cuesta no es lo mismo que saber que no cabe, y negar por defecto convertiría cada
    hueco de instrumentación en una degradación silenciosa del informe.
    """
    restante = queda()
    if restante is None or costo_estimado_s is None or costo_estimado_s <= 0:
        return True
    return restante > costo_estimado_s * MARGEN
