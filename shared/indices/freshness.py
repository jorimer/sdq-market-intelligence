"""Marca de frescura para rankings de entidades.

Un ranking de entidades casi nunca tiene a todas en el mismo corte: una deja de reportar,
otra publica tarde. Sin marcarlo, sus scores aparecen **comparables de igual a igual** y el
lector no tiene forma de saber que está mirando una foto vieja al lado de una actual.

Casos reales medidos el 2026-08-07, todos silenciosos hasta que se agregó esta marca:

* ISF — Autoseguro se rankeaba con estados de **2020** y Confederación del Canadá con los de
  **2023**, junto a 33 aseguradoras de 2024.
* ISARS — SeNaSa (la ARS pública más grande del país) y SEMMA en **2026-03** contra 2026-04
  del resto.

Banca ya lo resolvía por su cuenta (``stale``/``months_behind``); esto lleva el mismo criterio
a los demás motores sin que cada uno lo reimplemente.
"""
from typing import Any, Dict, List, Optional, Tuple

# Formato de período → unidad y cuántas unidades tiene un "salto" entre dos claves ordenadas.
_ANUAL, _MENSUAL = "años", "meses"


def _parse(period: Optional[str]) -> Optional[Tuple[str, int]]:
    """``"2024"`` → (anual, 2024) · ``"2026-05"`` → (mensual, 24317). None si no se reconoce.

    El entero es un contador absoluto en la unidad, así que restar dos da el atraso directo.
    """
    if not period or not isinstance(period, str):
        return None
    p = period.strip()
    if len(p) == 4 and p.isdigit():
        return _ANUAL, int(p)
    if len(p) >= 7 and p[4] == "-" and p[:4].isdigit() and p[5:7].isdigit():
        return _MENSUAL, int(p[:4]) * 12 + int(p[5:7])
    return None


def annotate_freshness(rows: List[Dict[str, Any]], period_key: str = "period") -> Optional[str]:
    """Añade ``stale`` / ``periods_behind`` / ``period_unit`` a cada fila, in-place.

    Devuelve el corte más reciente del panel (para exponerlo como ``period_end``), o None si
    ninguna fila trae un período reconocible.

    Períodos de formatos distintos en un mismo panel no se comparan entre sí: cada fila se
    mide contra el corte más reciente **de su propia unidad**. Mezclar años con meses daría un
    atraso inventado, y un número inventado es peor que no marcar nada.
    """
    parsed = {id(r): _parse(r.get(period_key)) for r in rows}
    maximos: Dict[str, int] = {}
    for p in parsed.values():
        if p and (p[0] not in maximos or p[1] > maximos[p[0]]):
            maximos[p[0]] = p[1]

    for r in rows:
        p = parsed[id(r)]
        if p is None:
            r["stale"], r["periods_behind"], r["period_unit"] = None, None, None
            continue
        unidad, valor = p
        atraso = maximos[unidad] - valor
        r["stale"], r["periods_behind"], r["period_unit"] = atraso > 0, atraso, unidad

    if not maximos:
        return None
    # El corte del panel es el de la unidad más frecuente (la dominante del ranking).
    unidad_dominante = max(maximos, key=lambda u: sum(1 for p in parsed.values() if p and p[0] == u))
    tope = maximos[unidad_dominante]
    return next((r.get(period_key) for r in rows
                 if (q := parsed[id(r)]) and q[0] == unidad_dominante and q[1] == tope), None)
