"""Cuándo empieza y cuándo cierra una etiqueta de período.

Vive en `shared/` y no dentro de un módulo porque la pregunta no es de nadie en particular:
la usan el registro (para saber si un corte de información cayó después del período que se
proyecta) y la macro (para ordenar cronológicamente y para descartar lo futuro).

⚠️ Hay DOS copias más de esto en el árbol —`modules/macro_monitor/service.py` y
`modules/trade_intel/products.py::_period_end_date`— escritas antes que este archivo. No se
unifican acá porque tocarlas es otro cambio; queda declarado para que la próxima que necesite
un tercer consumidor apunte a esta y no escriba una cuarta.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from typing import Optional

_Q_FIN = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_Q_INICIO = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}


def fin_del_periodo(period: Optional[str]) -> Optional[date]:
    """Fecha en que CIERRA la etiqueta: ``YYYY``, ``YYYY-MM``, ``YYYY-Qn``, ``YYYY-MM-DD``.

    ``None`` cuando no se puede resolver —un horizonte relativo como ``+4T``, o cualquier
    cosa que no sea un período— para que quien llame decida qué hacer. «No sé» y «cierra el
    31 de diciembre» son cosas distintas.

    El DÍA se resuelve PRIMERO: ``2026-03-07`` también empieza con algo que parece
    ``YYYY-MM``, y sin ese orden un día cerraría como si fuera el mes entero.
    """
    return _resolver(period, dia_final=True)


def inicio_del_periodo(period: Optional[str]) -> Optional[date]:
    """Fecha en que EMPIEZA la etiqueta. Un período es futuro si su inicio es posterior a
    hoy — así el período en curso se conserva y solo cae lo genuinamente futuro."""
    return _resolver(period, dia_final=False)


def _resolver(period: Optional[str], *, dia_final: bool) -> Optional[date]:
    if not period:
        return None
    p = str(period).strip().upper()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", p)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})", p)
    if m:
        y = int(m.group(1))
        return date(y, 12, 31) if dia_final else date(y, 1, 1)
    m = re.fullmatch(r"(\d{4})-Q([1-4])", p)
    if m:
        mo, dd = (_Q_FIN if dia_final else _Q_INICIO)[int(m.group(2))]
        return date(int(m.group(1)), mo, dd)
    m = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return date(y, mo, monthrange(y, mo)[1] if dia_final else 1)
    return None
