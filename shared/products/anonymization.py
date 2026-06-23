"""Sensor de anonimización de Pulse — doctrina no negociable.

Pulse NUNCA emite identificadores de entidad. Este sensor es **sector-agnóstico**:
recorre el ``payload`` del snapshot de sistema y falla si encuentra (a) una clave
reservada que suele cargar nombres, o (b) cualquier nombre del roster del sector
embebido en un valor de texto. Lo corre el ensamblador antes de narrar/renderizar
un nivel ``system``; cada sector aporta su roster vía ``ProductSnapshot.entity_roster``.
"""
from __future__ import annotations

from typing import Iterable

# Claves que típicamente cargan identificadores — prohibidas en un snapshot de sistema.
_FORBIDDEN_KEYS = frozenset({
    "entity_name", "bank_name", "name", "names", "entity", "entities",
    "top10", "top_10", "peers", "roster", "ranking", "rankings",
})


# Longitud mínima de un nombre del roster para hacer match por substring. Nombres
# muy cortos (acrónimos de 1-3 letras o palabras genéricas como "Banco") generarían
# falsos positivos contra prosa legítima. Trade-off precisión/recall documentado.
_MIN_ROSTER_LEN = 4


class AnonymizationError(ValueError):
    """Se filtró un identificador de entidad en un producto Pulse."""


def enforce_anonymized(payload: object, *, entity_roster: Iterable[str] = ()) -> None:
    """Lanza ``AnonymizationError`` si el payload de un Pulse no está anonimizado.

    Dos verificaciones:
      1. Claves reservadas (``_FORBIDDEN_KEYS``) presentes en cualquier nivel.
      2. Cualquier nombre del roster del sector (de longitud ≥ ``_MIN_ROSTER_LEN``)
         contenido (case-insensitive) en un valor de texto.
    """
    roster = [n.strip() for n in entity_roster
              if n and len(n.strip()) >= _MIN_ROSTER_LEN]
    roster_lower = [n.lower() for n in roster]

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
                    raise AnonymizationError(
                        f"Pulse no puede emitir identificadores: clave reservada "
                        f"'{key}' presente en {path or 'snapshot'}."
                    )
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, (list, tuple)):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            low = node.lower()
            for original, name in zip(roster, roster_lower):
                if name and name in low:
                    raise AnonymizationError(
                        f"Pulse no puede emitir identificadores: el nombre "
                        f"'{original}' aparece en {path or 'snapshot'}."
                    )

    walk(payload, "")
