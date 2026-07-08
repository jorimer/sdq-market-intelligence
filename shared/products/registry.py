"""Catálogo de los 10 productos sectoriales + registro de implementaciones.

Anti-Frankenstein: este módulo NO importa ningún módulo de sector. El catálogo es
data pura (los 10 sectores del spec §2). Cada sector que implementa el contrato se
**auto-registra** vía ``register_product`` al importarse (mismo patrón que la consola
de Operaciones), y el monitor lo resuelve con ``get_product``. Un sector del catálogo
sin implementación registrada → el monitor lo muestra como pendiente de cableado
(readiness 0), nunca inventado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.contract import SectorProduct


@dataclass(frozen=True)
class CatalogEntry:
    """Entrada declarativa del catálogo (data pura, sin código de sector)."""

    sector_key: str
    display_name: str
    module_hint: str        # módulo(s) que lo cablean (informativo)
    source: str             # fuente autoritativa (el foso)


# Los productos sectoriales (10 del spec §2 + pensiones/SIPEN). Orden = ejecución de P4.
PRODUCT_CATALOG: List[CatalogEntry] = [
    CatalogEntry("banking", "SDQ Banking Intelligence", "banking_score", "SIB · fiduciaria · BCRD"),
    CatalogEntry("macro", "SDQ Macro & Country Risk", "macro_monitor · macro_political_risk",
                 "BCRD · DIGEPRES · WGI/WDI · GDELT"),
    CatalogEntry("trade", "SDQ Trade & Logistics", "trade_intel", "DGA · BCRD"),
    CatalogEntry("tourism", "SDQ Tourism Intelligence", "sector_intel (o propio)",
                 "BCRD turismo · ASONAHORES · MITUR"),
    CatalogEntry("free_zones", "SDQ Free Zones & Manufacturing", "sector_intel (o propio)",
                 "CNZFE · ONE · datos.gob.do"),
    CatalogEntry("energy", "SDQ Energy Intelligence", "propio (probable)",
                 "SIE · CNE · Organismo Coordinador"),
    CatalogEntry("telecom", "SDQ Telecom Intelligence", "propio (probable)", "INDOTEL"),
    CatalogEntry("construction", "SDQ Construction Intelligence", "construction_intel",
                 "MIVHED · BCRD"),
    CatalogEntry("agribusiness", "SDQ Agribusiness", "sector_intel (o propio)",
                 "Min. Agricultura · BAGRÍCOLA · ONE"),
    CatalogEntry("esg", "SDQ ESG & Climate", "esg_climate", "ONE · Medio Ambiente · IPCC · SIE"),
    CatalogEntry("pension", "SDQ Pensiones (SIPEN)", "pension_intel", "SIPEN · ADAFP"),
    CatalogEntry("insurance", "SDQ Seguros (SIS)", "insurance_intel",
                 "SIS · SISALRIL · datos.gob.do"),
    # Producto de POLÍTICA MONETARIA (nacional): evaluación de la postura del BCRD +
    # trayectoria de la TPM + pronóstico/sesgo del modelo (regla de Taylor + XGBoost).
    CatalogEntry("monetary_policy", "SDQ Política Monetaria", "macro_monitor",
                 "BCRD — Comunicados de Política Monetaria · series macro"),
    # Producto AGREGADO (no un sector): la estructura de la economía por sector
    # (importancia económica + contribución al crecimiento). Para clientes institucionales.
    CatalogEntry("economic_structure", "SDQ Sectoral Structure · Estructura de la Economía",
                 "sector_intel", "BCRD · PIB por sectores de origen (Valor Agregado)"),
]

CATALOG_BY_KEY: Dict[str, CatalogEntry] = {e.sector_key: e for e in PRODUCT_CATALOG}

# Factories registradas por los módulos al importarse: sector_key → (db) -> SectorProduct.
ProductFactory = Callable[[Optional[Session]], SectorProduct]
_REGISTRY: Dict[str, ProductFactory] = {}


def register_product(sector_key: str, factory: ProductFactory) -> None:
    """Registra la implementación de un sector (idempotente). La llama el módulo del
    sector al importarse — NUNCA este paquete a un módulo."""
    if sector_key not in CATALOG_BY_KEY:
        raise ValueError(f"'{sector_key}' no está en el catálogo de productos.")
    _REGISTRY[sector_key] = factory


def get_product(sector_key: str, db: Optional[Session] = None) -> Optional[SectorProduct]:
    """Instancia el ``SectorProduct`` del sector si está implementado; si no, ``None``."""
    factory = _REGISTRY.get(sector_key)
    return factory(db) if factory else None


def is_implemented(sector_key: str) -> bool:
    return sector_key in _REGISTRY


def registered_sectors() -> List[str]:
    return [e.sector_key for e in PRODUCT_CATALOG if e.sector_key in _REGISTRY]
