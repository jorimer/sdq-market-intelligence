"""Data Registry — capa de LECTURA que agrega la señal por-variable de los productos.

Motor de Research Custom · Fase 1 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.1).

Qué resuelve: la verdad por-variable (qué mide cada eje, con qué peso, con qué
fuente, con qué cadencia, y su estado **real / rúbrica / brecha**) hoy vive
fragmentada en dos formatos por-módulo —el mapa ``sources`` "live"/"rubric" de los
paneles (`assemble_*_dataset`) y el ``breakdown.provenance`` "real"/"brecha" de los
índices de puntaje. Este paquete la **normaliza** en un solo esquema consultable.

Anti-Frankenstein (CLAUDE.md): ``shared/registry`` NUNCA importa un módulo de sector.
Recorre el catálogo (`shared/products/registry`) y llama a cada producto por su
contrato —igual que ``shared/products/audit.build_audit``—, usando el método
OPCIONAL ``variable_signals`` que cada producto expone. Un producto que aún no lo
implemente degrada con honestidad a su señal a-nivel-producto (`data_signals`), nunca
se fabrica granularidad que no existe. Es una capa de agregación de lectura para un
consumidor transversal (el motor de research), no acoplamiento de escritura entre
módulos.
"""
from shared.registry.signals import (
    GAP,
    REAL,
    RUBRIC,
    AxisRegistry,
    DataRegistry,
    VariableSignal,
    normalize_state,
)

__all__ = [
    "REAL",
    "RUBRIC",
    "GAP",
    "VariableSignal",
    "AxisRegistry",
    "DataRegistry",
    "normalize_state",
]
