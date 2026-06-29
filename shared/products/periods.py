"""Períodos disponibles por producto — alimenta el selector de período del reporte.

Cada ``SectorProduct`` PUEDE implementar ``available_periods() -> List[str]`` (más reciente
primero) para que el catálogo muestre un selector con SUS períodos reales, en vez de heredar
el período global del topbar (trimestral, que no casa con productos anuales). El endpoint
``/products/{sector}/periods`` lo detecta por ``getattr`` (igual que ``scope_options``).

``distinct_periods`` es un helper defensivo: cualquier fallo devuelve ``[]`` → el front
oculta el selector y cae al período global (comportamiento previo). Nunca rompe el producto.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import List


def period_sort_key(p: str):
    """Orden cronológico robusto a formatos mixtos: ``2025`` (anual), ``2025-Q4``,
    ``2025-03``, ``2025-03-31`` (fecha ISO). El año desnudo ordena DESPUÉS de cualquier
    trimestre/mes de ese año (sentinela 13), como la cifra anual completa."""
    s = str(p)
    m = re.match(r"(\d{4})(?:-Q([1-4])|-(\d{2})(?:-(\d{2}))?)?", s)
    if not m:
        return (0, 0, 0)
    year = int(m.group(1))
    if m.group(2):  # trimestre → mes representativo
        month, day = int(m.group(2)) * 3, 0
    elif m.group(3):  # mes (y día opcional)
        month, day = int(m.group(3)), int(m.group(4)) if m.group(4) else 0
    else:  # año desnudo → después de cualquier sub-período del año
        month, day = 13, 0
    return (year, month, day)


def distinct_periods(db, column, *, where=None, limit: int = 40) -> List[str]:
    """Períodos distintos (más reciente primero) de una columna de período/fecha.

    *column* es una columna SQLAlchemy (``Model.period`` o ``Model.period_end``). Las
    fechas se serializan a ISO. Devuelve ``[]`` ante cualquier error (defensivo)."""
    try:
        q = db.query(column).distinct()
        if where is not None:
            q = q.filter(where)
        out = set()
        for row in q.all():
            v = row[0]
            if v is None:
                continue
            out.add(v.isoformat() if isinstance(v, (date, datetime)) else str(v))
        return sorted(out, key=period_sort_key, reverse=True)[:limit]
    except Exception:  # noqa: BLE001 — el selector de período nunca debe romper el producto
        return []
