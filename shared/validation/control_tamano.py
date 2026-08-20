"""Contra qué CONTROL se lee la cifra de un motor de validación.

**El caso, dos veces en dos motores distintos.** Un score que ordena entidades de tamaños muy
distintos queda mecánicamente correlacionado con el tamaño, y el Gini no distingue «el índice
ordena» de «el tamaño ordena y el índice lo copia». Las dos lecturas son opuestas y llevan a
arreglos incompatibles.

- **`sector_intel` (IAI, Fase 3).** Contra intensidad de IED el índice daba −0,321 … y el
  tamaño SOLO daba −0,323: el signo era del deflactor, no del índice. Contra nivel, +0,287
  contra **+0,377** del tamaño solo. Veredicto: el IAI no agrega poder sobre el tamaño.
- **`banking_score` (2026-08-19).** `solidez` daba −0,1944; comparando dentro del mismo tramo
  de tamaño, −0,0055 con el IC cruzando cero. Y el activo total solo ordena el desenlace con
  **+0,413** — mejor que el score entero (+0,16).

En los dos casos el control cambió el veredicto, y en los dos existía solo porque alguien se
acordó. La doctrina del repo es explícita para esta situación: cuando un defecto se repite
entre motores, la cura es un **test estructural**, no una lección escrita.

**La regla.** Todo motor registrado en `shared.validation.frescura.MOTORES` declara
`control_de_tamano`: o la clave donde el control VIAJA en su reporte, o un motivo de la lista
cerrada de abajo. El silencio no es una opción — un motor que calla su control se lee como si
lo hubiera hecho.

**`no_medido` no es una excusa, es un pendiente con nombre.** Obliga a nombrar la variable de
tamaño que se usaría, para que la brecha se pueda cerrar en vez de encogerse de hombros. Es la
misma forma que `dato_pendiente` en `OBSTACULOS_BACKTEST`, que exige decir QUÉ dato falta.
"""
from dataclasses import dataclass
from typing import Dict, Optional

# Lista CERRADA. Un motivo nuevo se agrega acá con su explicación, no en el sitio de registro:
# así el catálogo de razones válidas se lee de un solo lugar y no se inventa una por motor.
MOTIVOS_SIN_CONTROL: Dict[str, str] = {
    "sujeto_unico": (
        "el panel tiene un solo sujeto (el país), así que no hay corte transversal que "
        "ordenar y tampoco hay tamaños que confundan"
    ),
    "tamano_no_observable": (
        "el panel no trae ninguna variable de tamaño de sus sujetos, así que el control no se "
        "puede computar con lo que hay"
    ),
    "tamano_es_el_score": (
        "el score ES una medida de tamaño, así que controlarlo por tamaño sería medirlo "
        "contra sí mismo"
    ),
    "no_medido": (
        "el control corresponde y todavía no se computó. Obliga a nombrar la variable que se "
        "usaría: es un pendiente con nombre, no una exención"
    ),
}


@dataclass(frozen=True)
class ControlDeTamano:
    """O el control viaja en el reporte (``clave``), o se declara por qué no (``motivo``).

    Nunca las dos, nunca ninguna: es la diferencia entre «lo medimos» y «no corresponde», y
    confundirlas es exactamente lo que este contrato existe para impedir.
    """

    #: Clave del reporte donde viaja el control. La cifra del control tiene que estar AHÍ, no
    #: en un documento: un número que hay que ir a buscar a otro lado no se lee junto al que
    #: acota, y entonces no acota nada.
    clave: Optional[str] = None
    #: Uno de ``MOTIVOS_SIN_CONTROL``.
    motivo: Optional[str] = None
    #: Con ``motivo="no_medido"``, la variable de tamaño que se usaría (p. ej.
    #: ``"activos_totales"``, ``"primas_suscritas"``, ``"PIB corriente"``).
    variable: Optional[str] = None
    #: Contexto libre: qué se sabe hoy, o por qué el motivo aplica en este panel.
    nota: Optional[str] = None

    @property
    def publicado(self) -> bool:
        return bool(self.clave)
