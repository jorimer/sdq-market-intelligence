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


# La prosa que los reportes copian vive acá, no incrustada en cada dict: un literal partido
# por ancho de línea deja de existir en el fuente aunque el valor sea correcto.
NOTA_CONTROL = (
    "el MISMO desenlace sobre el MISMO panel, ordenado solo por el tamaño del sujeto. Es la "
    "vara contra la que se lee la cifra del score: si el tamaño solo alcanza el mismo poder, "
    "el score no está agregando nada por encima de cuán grande es el sujeto"
)
VEREDICTO_TAMANO_ALCANZA = (
    "el tamaño SOLO ordena igual o mejor que el score: sobre este panel el score no agrega "
    "poder discriminante por encima del tamaño del sujeto"
)
VEREDICTO_SCORE_SUPERA = (
    "el score ordena mejor que el tamaño solo: la discriminación no se explica por cuán "
    "grande es el sujeto"
)
VEREDICTO_CONTROL_NO_EVALUABLE = (
    "no evaluable: falta el Gini del score o el del tamaño, así que no hay comparación que "
    "hacer. No es «el control salió bien»"
)


def medir_control_de_tamano(
    tamanos: "list", labels: "list", gini_del_score: Optional[float], variable: str,
    n_boot: int = 1000, nota_extra: Optional[str] = None,
) -> Dict[str, object]:
    """El mismo desenlace ordenado SOLO por tamaño, con su veredicto computado.

    *tamanos* entra con la MISMA convención que el score del motor (valor alto = sujeto
    "mejor" o más grande), así que su Gini se lee en la misma escala y se compara de frente.
    Los sujetos sin tamaño quedan fuera y se cuentan: un control computado sobre otro universo
    no acota nada.

    El veredicto compara MAGNITUDES (|Gini|), no signos: un control que ordena al revés con la
    misma fuerza también explica la cifra del score — es lo que pasó con el IAI, donde el
    deflactor producía el −0,32 entero.
    """
    from shared.validation.metrics import gini_bootstrap_ci

    pares = [(float(t), int(lab)) for t, lab in zip(tamanos, labels) if t is not None]
    base: Dict[str, object] = {"variable": variable,
                               "nota": NOTA_CONTROL + (f" — {nota_extra}" if nota_extra else "")}
    if not pares or len({lab for _t, lab in pares}) < 2:
        return {**base, "gini": None, "gini_ci": None, "n": len(pares),
                "veredicto": VEREDICTO_CONTROL_NO_EVALUABLE,
                "motivo": "el panel no trae el tamaño de sus sujetos, o no tiene las dos "
                          "clases del desenlace: el control no se puede computar"}
    g, lo, hi = gini_bootstrap_ci([t for t, _l in pares], [lab for _t, lab in pares],
                                  n_boot=n_boot)
    alcanza = (g is not None and gini_del_score is not None
               and abs(g) >= abs(gini_del_score))
    return {
        **base,
        "gini": None if g is None else round(g, 4),
        "gini_ci": None if g is None or lo is None or hi is None else [round(lo, 4),
                                                                      round(hi, 4)],
        "n": len(pares),
        "gini_del_score": gini_del_score,
        "el_tamano_alcanza_al_score": bool(alcanza),
        "veredicto": (VEREDICTO_CONTROL_NO_EVALUABLE if g is None or gini_del_score is None
                      else VEREDICTO_TAMANO_ALCANZA if alcanza else VEREDICTO_SCORE_SUPERA),
    }
