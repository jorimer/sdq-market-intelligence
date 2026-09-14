"""Lectura de los campos de un deal: la MISMA validación para el registro curado y el automático.

Vivía como helpers privados de `api/router.py` (`_enum`, `_bool`, `_num`, `_equity`). Se mudaron
acá sin cambio de comportamiento cuando el scoring empezó a guardar sus corridas: dos copias de
la validación divergen, y un sector que una acepta y la otra rechaza es un hueco que no se ve.
El router conserva los nombres viejos como alias.
"""
from __future__ import annotations

from typing import Any, Optional


def enum_de(enum_cls: Any, val: Any, default: Any = None) -> Any:
    """El miembro del enum cuyo valor es *val* (sin distinguir mayúsculas), o *default*."""
    v = (str(val).strip().lower() if val is not None else "")
    try:
        return enum_cls(v) if v else default
    except ValueError:
        return default


def bool_de(val: Any) -> Optional[bool]:
    s = str(val).strip().lower()
    if s in ("1", "true", "sí", "si", "yes", "cerrado"):
        return True
    if s in ("0", "false", "no", "perdido"):
        return False
    return None


def num_de(val: Any) -> Optional[float]:
    s = str(val).strip() if val is not None else ""
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def equity_de(val: Any) -> Optional[float]:
    """`equity_required_pct` va a `Numeric(5,2)`: se acota a [0, 999.99] para no reventar en
    PostgreSQL (en SQLite pasa en silencio, gap de paridad conocido)."""
    v = num_de(val)
    return None if v is None else max(0.0, min(999.99, v))
