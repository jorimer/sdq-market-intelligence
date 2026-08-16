"""Agregador del Data Registry — recorre el catálogo de productos y normaliza.

Mismo patrón de lectura resiliente que ``shared/products/audit.build_audit``: por
cada entrada del catálogo instancia el ``SectorProduct`` y le pide su señal
por-variable a través del método OPCIONAL ``variable_signals``. Un producto que aún
no lo implemente —o cuya lectura falle (tabla ausente, transacción abortada)— degrada
SOLO ese eje a su señal a-nivel-producto (`data_signals`), con la sesión revertida
para no envenenar al siguiente eje (Postgres). Nunca tumba el registro completo ni
fabrica granularidad inexistente.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented
from shared.registry.signals import (
    COVERAGE_INDEX,
    COVERAGE_KINDS,
    GAP,
    REAL,
    AxisRegistry,
    DataRegistry,
    VariableSignal,
)

logger = logging.getLogger("sdq.registry")


def _product_level_fallback(entry, data) -> AxisRegistry:
    """Eje degradado: una sola señal derivada de ``data_signals`` (nivel producto).

    Honesto por construcción: declara que la granularidad por-variable no está
    expuesta aún y ancla la cobertura al ``coverage`` real de la fuente. El motor de
    research lee esto como "el eje mide algo real pero no puedo descomponerlo por
    variable todavía" — una brecha de INSTRUMENTACIÓN declarada, no un dato inventado.
    """
    cov = max(0.0, min(1.0, float(getattr(data, "coverage", 0.0) or 0.0)))
    state = REAL if cov > 0.0 else GAP
    sig = VariableSignal(
        key="_axis", label=f"{entry.display_name} (agregado)", state=state,
        dimension="", weight=1.0,
        source=", ".join(getattr(data, "sources", ()) or ()) if state == REAL else "",
        cadence=getattr(data, "cadence", "unknown") or "unknown",
        value=None, real_fraction=cov,
        note=("granularidad por-variable no expuesta aún (el eje no implementa "
              "variable_signals); cobertura a-nivel-fuente"),
    )
    return AxisRegistry(
        sector_key=entry.sector_key, display_name=entry.display_name,
        source=entry.source, implemented=True, degraded=True,
        period=None, signals=(sig,),
        note=(getattr(data, "detail", "") or "").strip(),
    )


def _axis_registry(db: Optional[Session], entry) -> AxisRegistry:
    """Registro de un eje. Preferir ``variable_signals`` del producto; si no existe,
    fallback a-nivel-producto."""
    if not is_implemented(entry.sector_key):
        return AxisRegistry(
            sector_key=entry.sector_key, display_name=entry.display_name,
            source=entry.source, implemented=False, degraded=False,
            note="Pendiente de cableado: sin producto registrado.",
        )

    product = get_product(entry.sector_key, db)
    fn = getattr(product, "variable_signals", None)
    if not callable(fn):
        return _product_level_fallback(entry, product.data_signals())

    result = fn()  # -> {"period": str|None, "signals": [...], "coverage_kind": str} | [...]
    kind = COVERAGE_INDEX
    if isinstance(result, dict):
        period = result.get("period")
        signals = tuple(result.get("signals", ()))
        # Un eje declara otra semántica de cobertura SOLO si es de las conocidas: una cadena
        # libre acá volvería incomparable a un eje por un typo, y silenciosamente.
        declarado = result.get("coverage_kind")
        if declarado in COVERAGE_KINDS:
            kind = declarado
        elif declarado is not None:
            logger.warning("eje %s declaró coverage_kind desconocido: %r — se usa %s",
                           entry.sector_key, declarado, COVERAGE_INDEX)
    else:
        period, signals = None, tuple(result or ())

    if not signals:  # implementado pero sin señales este período → degradar honesto
        return _product_level_fallback(entry, product.data_signals())

    return AxisRegistry(
        sector_key=entry.sector_key, display_name=entry.display_name,
        source=entry.source, implemented=True, degraded=False,
        period=period, signals=signals, coverage_kind=kind,
    )


def _safe_axis_registry(db: Optional[Session], entry) -> AxisRegistry:
    """``_axis_registry`` resiliente: una lectura que falla degrada solo ese eje."""
    try:
        return _axis_registry(db, entry)
    except Exception as e:  # noqa: BLE001
        logger.warning("Registry del eje '%s' no disponible: %s", entry.sector_key, e)
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return AxisRegistry(
            sector_key=entry.sector_key, display_name=entry.display_name,
            source=entry.source, implemented=is_implemented(entry.sector_key),
            degraded=True, note="No evaluable ahora (señal del eje no disponible).",
        )


def build_data_registry(db: Optional[Session] = None) -> DataRegistry:
    """El Data Registry completo: la señal por-variable normalizada de todos los ejes."""
    axes: List[AxisRegistry] = [_safe_axis_registry(db, e) for e in PRODUCT_CATALOG]
    return DataRegistry(
        generated_at=datetime.now(timezone.utc).isoformat(),
        axes=tuple(axes),
    )
