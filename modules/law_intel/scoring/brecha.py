"""Lo que el informe NO puede medir, con quién debe producirlo y qué desbloquearía.

Esta es la sección que convierte una limitación en una lista de cosas accionables. El cliente
del producto no es quien quiere un informe: es quien tiene legitimación para exigir que el
dato exista. Por eso cada brecha viaja con su destinatario y con su rendimiento en cobertura.

**La recomendación es de PUBLICACIÓN, nunca de política.** Se puede decir «este indicador no
tiene fuente vigente y el artículo 41 asigna su producción al órgano rector». No se puede
decir qué debería hacer el Estado con el indicador. Recomendar transparencia es compatible
con ser independiente; recomendar política no lo es, y la frontera vive acá y no en el
criterio de quien redacta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from modules.law_intel.bindings import Binding
from modules.law_intel.campo import RESPONSABLE_POR_MOTIVO
from modules.law_intel.registro import Indicador

# Los tipos se distinguen porque se exigen distinto. «No existe el dato» se pide al productor
# de estadística; «existe la obligación de publicar y está incumplida» se exige con el
# instrumento que la propia ley creó, y es el reclamo más fuerte: no pide nada nuevo.
TIPOS = {
    "sin_binding": "ninguna serie propuesta mide este indicador",
    "binding_sin_verificar": "hay serie candidata y nadie la comprobó contra la fuente",
    "fuente_descartada": "se evaluó una fuente y no mide lo que el eje afirma medir",
    "escala_no_medible": "la ley fija la meta en una escala que no admite diferencia",
}

# De quién es la brecha SEGÚN LA ESTRUCTURA del binding. Es un respaldo, no la respuesta:
# se usa solo cuando el indicador no tiene motivo declarado en el campo.
#
# **Por qué no alcanza.** Un binding `propuesto` con `linea_base_no_reproduce` cae acá como
# `binding_sin_verificar` → «sdq», y no es deuda nuestra: es EL HALLAZGO —la línea base que
# la ley fija no reproduce contra la serie de su propio emisor— y el trabajo está hecho. Con
# este mapa solo, la plataforma decía «20 brechas son de SDQ» mientras el campo decía «2», y
# el informe generado citaba una u otra según la sección. La autoridad es
# `campo.RESPONSABLE_POR_MOTIVO`; esto queda para el indicador que todavía no tiene casilla.
RESPONSABLE_POR_ESTRUCTURA = {
    "sin_binding": "sdq",
    "binding_sin_verificar": "sdq",
    "fuente_descartada": "sdq",
    "escala_no_medible": "instrumento",
}
RESPONSABLE = RESPONSABLE_POR_ESTRUCTURA          # nombre anterior, se conserva


@dataclass(frozen=True)
class Brecha:
    indicador: str
    nombre: str
    eje: int
    tipo: str
    responsable: str
    detalle: Optional[str] = None
    serie_candidata: Optional[str] = None
    #: El motivo declarado en el campo, cuando existe. Es lo que decide `responsable`, y viaja
    #: al informe para que la atribución se pueda comprobar en vez de creerse.
    motivo_declarado: Optional[str] = None


def brechas(indicadores: Sequence[Indicador],
            bindings: Dict[str, Binding],
            motivos: Optional[Dict[str, str]] = None) -> List[Brecha]:
    """Las brechas de medición, con la atribución que declara el campo.

    `motivos` es `{indicador: estado_del_campo}`. Cuando un indicador lo trae, **manda sobre
    la estructura del binding**: un `propuesto` con `linea_base_no_reproduce` no es trabajo
    pendiente nuestro por más que su binding no esté verificado.
    """
    motivos = motivos or {}
    out: List[Brecha] = []
    for ind in indicadores:
        b = bindings.get(ind.id)
        if b and b.cuenta:
            continue
        if not ind.admite_delta:
            tipo, detalle, serie = "escala_no_medible", (
                f"la meta es de escala '{ind.escala}'; se evalúa por juicio, no por delta"), None
        elif b is None:
            tipo, detalle, serie = "sin_binding", None, None
        elif b.estado == "descartado":
            tipo, detalle, serie = "fuente_descartada", b.motivo_descarte, b.serie
        else:
            tipo, detalle, serie = "binding_sin_verificar", b.nota_comparabilidad, b.serie
        motivo = motivos.get(ind.id)
        responsable = (RESPONSABLE_POR_MOTIVO.get(motivo) if motivo
                       else None) or RESPONSABLE_POR_ESTRUCTURA[tipo]
        out.append(Brecha(ind.id, ind.nombre, ind.eje, tipo, responsable, detalle, serie,
                          motivo_declarado=motivo))
    return out


def desbloqueo(brechas_: Sequence[Brecha]) -> List[Dict[str, object]]:
    """Cuántos indicadores desbloquea cada acción, agrupadas por lo que hay que hacer.

    Es el mismo cómputo que la sugerencia interna de fuentes, con otro destinatario: hacia
    adentro dice «conectar esto sube la cobertura»; hacia el cliente, «exigir que se publique
    esto sube la cobertura». Un solo join, dos audiencias — y en los dos casos la cifra es el
    delta, no una promesa.
    """
    por_accion: Dict[str, List[str]] = {}
    for b in brechas_:
        if b.tipo == "escala_no_medible":
            continue          # no la desbloquea ninguna fuente: la escala es de la ley
        clave = (f"verificar la serie {b.serie_candidata}" if b.serie_candidata
                 else f"identificar una fuente para el indicador {b.indicador}")
        por_accion.setdefault(clave, []).append(b.indicador)
    # Se ordena sobre las tuplas y recién después se arma el dict: ordenar dicts obliga a
    # castear valores heterogéneos y el tipo se pierde por el camino.
    ordenadas = sorted(por_accion.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"accion": k, "desbloquea": len(v), "indicadores": sorted(v)}
            for k, v in ordenadas]


def resumen(brechas_: Sequence[Brecha], total_ley: int) -> Dict[str, object]:
    por_tipo: Dict[str, int] = {}
    por_responsable: Dict[str, int] = {}
    for b in brechas_:
        por_tipo[b.tipo] = por_tipo.get(b.tipo, 0) + 1
        por_responsable[b.responsable] = por_responsable.get(b.responsable, 0) + 1
    return {
        "total_indicadores_ley": total_ley,
        "con_brecha": len(brechas_),
        "por_tipo": dict(sorted(por_tipo.items())),
        # Sin este corte, el informe le imputa al Estado huecos que son nuestros.
        "por_responsable": dict(sorted(por_responsable.items())),
        "de_donde_sale_la_atribucion": (
            "Del motivo declarado en el campo del expediente, no de si el binding está "
            "verificado. Un binding propuesto cuya línea base legal no reproduce es un "
            "HALLAZGO sobre la ley, no trabajo pendiente de esta firma."),
        "advertencia_sobre_por_tipo": (
            "`por_tipo` clasifica por la ESTRUCTURA del binding y NO es la composición de "
            "los indicadores sin veredicto: esa es `estado_del_campo_computado.por_estado`, "
            "y es la única que se cita. Las dos parten la misma población con criterios "
            "distintos y sus conteos no coinciden."),
        "nota": ("`escala_no_medible` no es una falla de nadie: la ley fija esas metas en "
                 "palabras o como umbral, y ninguna fuente las vuelve restables."),
    }
