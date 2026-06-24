"""Contrato uniforme que cada sector implementa — ``Protocol`` ``SectorProduct``.

Anti-Frankenstein: el framework (``shared/products``) nunca importa un módulo de
sector. Cada sector implementa este ``Protocol`` y se lo entrega al ensamblador y
al monitor de readiness. Onboarding del sector #11 = implementar este contrato +
su manifiesto + sus señales, **sin tocar el framework ni el motor genérico**.

Las señales (``DataHealth``, ``ValidationState``) son valores livianos que el
monitor de readiness (P1) consume para los gates G1 y G5. Se definen aquí —junto
al contrato que las produce— y no acoplan a ninguna DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

from shared.products.manifest import SectorProductManifest
from shared.products.tiers import ProductTier


# ─── Señales de readiness (consumidas por el monitor en P1) ────────────


@dataclass(frozen=True)
class DataHealth:
    """Salud de la ingesta de la fuente autoritativa (alimenta G1 · Data).

    ``coverage`` y ``freshness`` se normalizan a [0,1] en el monitor; aquí se
    reportan crudos para trazabilidad (linaje hacia la señal real).
    """

    coverage: float                       # cobertura [0,1] de la fuente esperada
    freshness_days: Optional[int] = None  # antigüedad del dato más reciente (días)
    sources: Tuple[str, ...] = ()         # fuentes que respaldan el dato
    detail: str = ""                      # nota legible (trazabilidad)
    # Cadencia de publicación de la fuente — escala los umbrales de frescura del
    # monitor. Default "quarterly" = comportamiento histórico (banking/trade). Las
    # fuentes anuales rezagadas por naturaleza (ND-GAIN, WGI, cuentas nacionales)
    # declaran "annual" para no ser falsamente penalizadas como obsoletas.
    cadence: str = "quarterly"            # "monthly" | "quarterly" | "annual"


@dataclass(frozen=True)
class ValidationState:
    """Estado de validación/QA + doctrina del sector (alimenta G5 · Validación)."""

    approved: bool                # doctrina firmada / QA aprobado
    score: float = 0.0            # [0,1] — fuerza de la validación (backtest, outcomes)
    notes: str = ""


@dataclass(frozen=True)
class ProductSnapshot:
    """Datos ya calculados que un nivel necesita para narrar y renderizar.

    Estructura deliberadamente abierta (``payload``) porque cada sector tiene su
    propia forma de scoring; lo común es el sobre: granularidad, período y, para
    Insight/Deep Dive, la entidad nombrada. Para Pulse (``system``) ``entity_name``
    DEBE ser ``None`` y el ``payload`` no debe contener identificadores (lo verifica
    el sensor de anonimización en el ensamblador).
    """

    tier: ProductTier
    period: str
    payload: Dict
    entity_name: Optional[str] = None
    # Roster de entidades del sector — el sensor de anonimización Pulse lo usa para
    # verificar que ningún nombre se filtró al agregado de sistema.
    entity_roster: Tuple[str, ...] = field(default=())


@runtime_checkable
class SectorProduct(Protocol):
    """Lo que cada módulo de sector expone al framework de productos.

    El ensamblador genérico (``assembler.assemble_product_report``) orquesta usando
    SOLO estos métodos; nunca conoce el sector concreto.
    """

    sector_key: str  # "banking", "macro", ...

    def product_manifest(self) -> SectorProductManifest:
        """Manifiesto declarativo de los 3 niveles del sector."""
        ...

    # ── Señales de readiness ──
    def data_signals(self) -> DataHealth: ...
    def has_engine(self) -> bool: ...
    def validation_state(self) -> ValidationState: ...

    # ── Producción de reporte por nivel ──
    def snapshot(self, tier: ProductTier, period: str,
                 scope: Optional[str] = None) -> ProductSnapshot:
        """Datos del nivel: agregado anonimizado (Pulse) o entidad nombrada."""
        ...

    async def narratives(self, tier: ProductTier, snapshot: ProductSnapshot,
                         lang: str = "es") -> Dict[str, str]:
        """``{section_key: texto}`` para las secciones del nivel (vía el motor compartido)."""
        ...

    async def render(self, tier: ProductTier, snapshot: ProductSnapshot,
                     narratives: Dict[str, str], *, sample: bool = False,
                     lang: str = "es", output_dir: Optional[str] = None) -> str:
        """Renderiza el reporte del nivel y devuelve el path. Reusa building blocks."""
        ...


def required_signal_methods() -> List[str]:
    """Métodos que un sector debe implementar para el monitor (test de contrato)."""
    return ["product_manifest", "data_signals", "has_engine", "validation_state",
            "snapshot", "narratives", "render"]
