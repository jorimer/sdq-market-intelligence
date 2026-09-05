"""Rúbrica de readiness G1-G5 — ¿qué tan listo está un producto (sector, nivel)?

Calcula el readiness desde las **señales reales del contrato** ``SectorProduct`` (no
hardcode): salud de datos, motor, narrativa, plantilla y validación. El resultado
(0–1) lo usa el gate de activación: un producto solo se expone al público si su
readiness cruza el umbral del nivel. Cada gate guarda su detalle (linaje hacia la
señal que lo originó) para trazabilidad.

Pesos (spec §3.1): G1 Data 30% · G2 Motor 25% · G3 Narrativa 15% · G4 Plantilla 15%
· G5 Validación 15%.

**Honestidad sobre qué mide cada gate hoy (P1):** G1 (datos) y G5 (validación) son
señales sustantivas (cobertura×frescura real; outcomes/QA del sector). G2/G3/G4 son, en
esta fase, señales **declarativas de presencia**: motor operativo (booleano), templates
del nivel declarados, y plantilla completa (secciones + reporte base). El ejercicio real
—correr el `numeric_guard` (G3), un smoke render del nivel (G4) y el último scoring OK
(G2)— se ejerce al GENERAR el producto, no en el cálculo de readiness en reposo, y queda
como refinamiento de una fase posterior. Es decir: un readiness alto dice "está cableado
y configurado", y el guard/render efectivos se validan en la producción del reporte.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

from shared.products.contract import DataHealth, SectorProduct
from shared.registry.signals import COVERAGE_INSTRUMENT as _COVERAGE_INSTRUMENT
from shared.products.tiers import ProductTier

GATE_WEIGHTS: Dict[str, float] = {"g1": 0.30, "g2": 0.25, "g3": 0.15, "g4": 0.15, "g5": 0.15}

# Frescura: dato ≤ fresh = pleno; decae linealmente a 0 en stale. Los umbrales se
# escalan por la CADENCIA de la fuente: una fuente trimestral obsoleta a los ~400d,
# pero una ANUAL (ND-GAIN, WGI, cuentas nacionales) está al día con ~1-2 años de
# rezago por naturaleza — penalizarla con la curva trimestral sería un falso-stale.
FRESH_DAYS = 120          # back-compat: umbral "quarterly" (referenciado en tests)
STALE_DAYS = 400
_CADENCE_THRESHOLDS: Dict[str, tuple] = {
    "monthly": (45, 150),
    "quarterly": (FRESH_DAYS, STALE_DAYS),
    "annual": (730, 2190),   # pleno ≤ 2 años; obsoleto ≥ 6 años
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _freshness_factor(freshness_days: Optional[int], cadence: str = "quarterly") -> float:
    if freshness_days is None:
        return 0.5  # sin fecha → señal a medias (honesto, no 0 ni 1)
    fresh, stale = _CADENCE_THRESHOLDS.get(cadence, (FRESH_DAYS, STALE_DAYS))
    if freshness_days <= fresh:
        return 1.0
    if freshness_days >= stale:
        return 0.0
    return _clamp01((stale - freshness_days) / (stale - fresh))


#: Cobertura de INSTRUMENTO: `coverage` no dice qué fracción de nuestro índice tiene dato,
#: sino qué fracción de las metas que el instrumento evaluado se fijó estamos midiendo. La
#: constante se reexpone desde el registro para que las dos superficies no puedan divergir.
COVERAGE_INSTRUMENT = _COVERAGE_INSTRUMENT


def _cobertura_que_puntua(data: DataHealth) -> Tuple[float, str]:
    """La cobertura que entra al gate, y el linaje de por qué es ésa.

    Para un índice es la cruda: mide nuestro cableado, y castigarla es correcto. Para un
    instrumento —una ley— la cruda incluye en el denominador metas que **ningún esfuerzo
    nuestro puede medir**, porque el impedimento está en el texto legal o en el aparato
    estadístico del evaluado. Ahí el gate castigaría al producto por el hallazgo que lo hace
    valioso, y el techo del eje queda bajo el umbral de publicación: no cruza nunca.

    Se usa `coverage_efectiva` solo si el producto la DECLARA junto con su desglose. Sin el
    desglose no hay linaje que escribir, y una cobertura mejorada sin linaje es exactamente
    el descuento silencioso que esto no puede volverse. El detalle nombra las dos cifras
    siempre, para que el número crudo no desaparezca del rastro.
    """
    cruda = _clamp01(data.coverage)
    if getattr(data, "coverage_kind", "") != COVERAGE_INSTRUMENT:
        return cruda, ""
    efectiva = getattr(data, "coverage_efectiva", None)
    imposibles = getattr(data, "imposibles_por_el_instrumento", None)
    universo = getattr(data, "universo", None)
    if efectiva is None or not imposibles or not universo:
        return cruda, ""
    return _clamp01(efectiva), (
        f" (sobre lo medible: {data.medidas} de {universo - imposibles}; "
        f"{imposibles} de {universo} no los puede medir nadie — cruda={cruda:.2f})")


def compute_readiness(product: SectorProduct, tier: ProductTier) -> Dict[str, Any]:
    """Readiness (0–1) de ``(product.sector_key, tier)`` con desglose G1-G5 + linaje.

    Sector-agnóstico: solo usa el contrato. G1/G2/G5 son a nivel sector; G3/G4 dependen
    del nivel (secciones/templates del manifiesto).
    """
    level = product.product_manifest().require_level(tier)

    # G1 · Data — cobertura × frescura de la fuente autoritativa.
    data = product.data_signals()
    cadence = getattr(data, "cadence", "quarterly")
    cobertura, linaje = _cobertura_que_puntua(data)
    g1 = _clamp01(cobertura) * _freshness_factor(data.freshness_days, cadence)
    g1_detail = (f"cobertura={cobertura:.2f}{linaje} · frescura={data.freshness_days}d "
                 f"({cadence}) · {data.detail or ', '.join(data.sources)}")

    # G2 · Motor — señal declarativa: índice explicable operativo (booleano). El
    # "último scoring OK" efectivo se evidencia al generar, no acá.
    has_engine = bool(product.has_engine())
    g2 = 1.0 if has_engine else 0.0

    # G3 · Narrativa — señal declarativa: el nivel tiene CON QUÉ producir su prosa. Dos
    # formas válidas y excluyentes: templates del motor de IA, o prosa computada por código.
    # La segunda existe porque preguntar solo por templates penalizaba al eje que eligió el
    # camino MÁS riguroso: un informe de errores, coberturas de intervalos y una
    # reconciliación exacta no tiene nada que redactar, y un modelo redactándolo inventaría
    # justo los números que el informe existe para probar. El numeric_guard (0 violaciones)
    # se ejerce al GENERAR, no en el cálculo en reposo.
    g3 = 1.0 if (level.narrative_templates or level.prosa_computada) else 0.0
    g3_detail = (f"{len(level.narrative_templates)} templates declarados"
                 if level.narrative_templates
                 else ("prosa computada (sin motor de IA)" if level.prosa_computada
                       else "0 templates declarados"))

    # G4 · Plantilla — señal declarativa: el nivel declara secciones para renderizar.
    # El contrato GARANTIZA render() (banking con su generador rico; otros con el
    # renderer genérico), así que `base_report_type` es opcional y NO penaliza G4
    # (era un sesgo de banking). El smoke render efectivo se evidencia al generar.
    g4 = 1.0 if level.sections else 0.0
    g4_detail = (f"{len(level.sections)} secciones · "
                 + (f"base={level.base_report_type}" if level.base_report_type else "render genérico"))

    # G5 · Validación — outcomes/QA + doctrina firmada.
    val = product.validation_state()
    g5 = _clamp01(val.score) if val.approved else 0.0
    g5_detail = f"approved={val.approved} · score={val.score:.2f} · {val.notes}"
    # ESTADO ESTRUCTURAL de la validación retrospectiva, declarado por el producto. Se lee
    # de la CLASE y no del `ValidationState` para que un eje con varias ramas de retorno no
    # pueda declararlo en una y olvidarlo en otra — el hueco entra por la rama olvidada.
    estado = getattr(type(product), "ESTADO_BACKTEST", None) or val.backtest

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
            # Por qué el eje tiene o no validación retrospectiva. Va DENTRO de `detail`
            # porque es lo único del reporte que se persiste (`_upsert_readiness` guarda las
            # cinco puertas y el detalle): una clave hermana se computaba y se tiraba, y la
            # API —que sirve las filas guardadas— nunca la habría mostrado.
            "backtest": (asdict(estado) if estado is not None else None),
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
