"""Guards de insumo compartidos por los submodelos de scoring.

**El caso que lo motivó** (2026-08-20, encontrado por el diagnóstico de materialidad). Placidoiv
—agente de cambio— publica en producción:

===========================  =============  =======  ==========
indicador                    crudo          score    dimensión
===========================  =============  =======  ==========
``capitalizacion``           **−1.459,14**  0        solidez
``apalancamiento``           **−1,0685**    **100**  solidez
===========================  =============  =======  ==========

Una entidad con patrimonio NEGATIVO sacaba **100 sobre 100 en apalancamiento**, el mejor
puntaje posible. De ahí salía `solidez = 50` (el promedio de 0 y 100) y un `overall` de 26,25
en vez de un score de fondo.

**Por qué pasa.** `pasivos / patrimonio` con patrimonio negativo da un número NEGATIVO, y la
escala de ese indicador es invertida —menos apalancamiento es mejor— así que el clamp lo manda
al techo. El peor estado posible entra por la puerta del mejor.

**Y ya estaba resuelto en el motor de bancos.** `engine._sib_ratio_positive` rechaza un ratio
de capital no positivo desde `d4c3806` (2026-06-22), cuando el mismo defecto producía un swing
de 30 puntos en BPD. Los submodelos de cambiaria y fiduciaria —escritos después, como espejo
uno del otro— no lo copiaron. Es la enésima instancia de «un guard existe en un motor y falta
en el otro»; vive acá, en un solo lugar, para que el próximo submodelo lo importe en vez de
volver a olvidarlo.

**Dos tratos distintos, y la diferencia importa.** Un ratio cuyo denominador es el patrimonio
deja de ser interpretable cuando el patrimonio no es positivo, pero no todos significan lo
mismo:

- **Apalancamiento y solvencia** miden un estado prudencial: patrimonio no positivo ES el peor
  estado, y se puntúa 0. Declararlo no disponible dejaría que la dimensión se renormalice y
  **borraría** la insolvencia del score.
- **Rentabilidad sobre patrimonio (ROE)** con patrimonio negativo cambia de SIGNO: una entidad
  que pierde plata aparece rentable. Eso no es «el peor valor», es un número sin sentido, y se
  declara NO DISPONIBLE.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def patrimonio_es_positivo(valor: Optional[float]) -> bool:
    """True si el patrimonio sostiene un ratio que lo lleva en el denominador."""
    return valor is not None and float(valor) > 0


def peor_estado_prudencial(raw: float) -> Dict[str, Any]:
    """Indicador prudencial con patrimonio no positivo: el PEOR puntaje, y disponible.

    Disponible a propósito: si se declarara N/D, la dimensión se renormalizaría sobre los
    indicadores restantes y la insolvencia desaparecería del score en vez de hundirlo.
    """
    return {"raw": round(raw, 4), "score": 0.0, "available": True}


def no_interpretable(raw: float) -> Dict[str, Any]:
    """Ratio cuyo signo se invierte con patrimonio negativo: NO disponible.

    No es el peor valor —es un valor que miente—: con patrimonio negativo, una pérdida se lee
    como rentabilidad. Un hueco declarado es preferible a un número dado vuelta.
    """
    return {"raw": round(raw, 4), "score": 0.0, "available": False}
