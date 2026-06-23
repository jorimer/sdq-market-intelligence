"""Rúbrica de readiness G1-G5 — ¿qué tan listo está un producto (sector, nivel)?

Calcula el readiness desde las **señales reales del contrato** ``SectorProduct`` (no
hardcode): salud de datos, motor, narrativa, plantilla y validación. El resultado
(0–1) lo usa el gate de activación: un producto solo se expone al público si su
readiness cruza el umbral del nivel. Cada gate guarda su detalle (linaje hacia la
señal que lo originó) para trazabilidad.

Pesos (spec §3.1): G1 Data 30% · G2 Motor 25% · G3 Narrativa 15% · G4 Plantilla 15%
· G5 Validación 15%.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from shared.products.contract import SectorProduct
from shared.products.tiers import ProductTier

GATE_WEIGHTS: Dict[str, float] = {"g1": 0.30, "g2": 0.25, "g3": 0.15, "g4": 0.15, "g5": 0.15}

# Frescura: dato ≤ FRESH_DAYS = pleno; decae linealmente a 0 en STALE_DAYS.
FRESH_DAYS = 120
STALE_DAYS = 400


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _freshness_factor(freshness_days: Optional[int]) -> float:
    if freshness_days is None:
        return 0.5  # sin fecha → señal a medias (honesto, no 0 ni 1)
    if freshness_days <= FRESH_DAYS:
        return 1.0
    if freshness_days >= STALE_DAYS:
        return 0.0
    return _clamp01((STALE_DAYS - freshness_days) / (STALE_DAYS - FRESH_DAYS))


def compute_readiness(product: SectorProduct, tier: ProductTier) -> Dict[str, Any]:
    """Readiness (0–1) de ``(product.sector_key, tier)`` con desglose G1-G5 + linaje.

    Sector-agnóstico: solo usa el contrato. G1/G2/G5 son a nivel sector; G3/G4 dependen
    del nivel (secciones/templates del manifiesto).
    """
    level = product.product_manifest().require_level(tier)

    # G1 · Data — cobertura × frescura de la fuente autoritativa.
    data = product.data_signals()
    g1 = _clamp01(data.coverage) * _freshness_factor(data.freshness_days)
    g1_detail = (f"cobertura={data.coverage:.2f} · frescura={data.freshness_days}d · "
                 f"{data.detail or ', '.join(data.sources)}")

    # G2 · Motor — índice explicable operativo.
    has_engine = bool(product.has_engine())
    g2 = 1.0 if has_engine else 0.0

    # G3 · Narrativa — templates declarados para el nivel (el guard se ejerce al generar).
    g3 = 1.0 if level.narrative_templates else 0.0
    g3_detail = f"{len(level.narrative_templates)} templates declarados"

    # G4 · Plantilla — el nivel tiene secciones + reporte base para renderizar.
    if level.sections and level.base_report_type:
        g4 = 1.0
    elif level.sections:
        g4 = 0.5
    else:
        g4 = 0.0
    g4_detail = f"{len(level.sections)} secciones · base={level.base_report_type or '—'}"

    # G5 · Validación — outcomes/QA + doctrina firmada.
    val = product.validation_state()
    g5 = _clamp01(val.score) if val.approved else 0.0
    g5_detail = f"approved={val.approved} · score={val.score:.2f} · {val.notes}"

    gates = {"g1": _clamp01(g1), "g2": g2, "g3": g3, "g4": g4, "g5": _clamp01(g5)}
    readiness = sum(GATE_WEIGHTS[k] * v for k, v in gates.items())

    return {
        "sector_key": product.sector_key,
        "tier": tier.value,
        **gates,
        "readiness": round(_clamp01(readiness), 4),
        "weights": GATE_WEIGHTS,
        "detail": {
            "g1": g1_detail, "g2": "motor operativo" if has_engine else "sin motor",
            "g3": g3_detail, "g4": g4_detail, "g5": g5_detail,
        },
    }


def empty_readiness(sector_key: str, tier: ProductTier, reason: str) -> Dict[str, Any]:
    """Readiness 0 para un sector declarado pero aún NO cableado (sin producto).

    Honesto: el monitor lo muestra como pendiente de cableado, no activable. NUNCA se
    inventa un gate para subir el readiness.
    """
    gates = {"g1": 0.0, "g2": 0.0, "g3": 0.0, "g4": 0.0, "g5": 0.0}
    return {
        "sector_key": sector_key, "tier": tier.value, **gates,
        "readiness": 0.0, "weights": GATE_WEIGHTS,
        "detail": {k: reason for k in gates},
    }
