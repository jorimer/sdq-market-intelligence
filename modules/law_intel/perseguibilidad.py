"""Qué indicador se puede todavía perseguir, y de quién depende que se cierre.

El campo (`modules.law_intel.campo`) responde OTRA pregunta: por qué un indicador no tiene
veredicto. Es una taxonomía de causas y sirve para que ninguno quede en silencio. Pero un
lector que quiere decidir dónde poner el próximo día de trabajo no necesita la causa: necesita
saber **de quién depende**, y esa respuesta agrupa causas muy distintas y separa causas que
parecen la misma.

Ejemplo de lo primero: «no hemos buscado la fuente» y «el descarte se apoya en una hipótesis
que nadie midió» son causas distintas y las dos son trabajo nuestro. Ejemplo de lo segundo:
dos indicadores igualmente descartados pueden estar, uno, esperando que identifiquemos un
universo —tarea nuestra— y el otro esperando que el Estado vuelva a levantar una encuesta que
dejó de hacer, que no es tarea de nadie acá.

**Por qué se computa y no se escribe.** Una tabla de «qué falta» envejece en cuanto alguien
promueve un indicador, y la que envejece mal es justamente la que se usa para planificar. Esta
clasificación sale del expediente cada vez que se pide.
"""
from __future__ import annotations

from typing import Any, Dict, List

from modules.law_intel.bindings import cargar_bindings
from modules.law_intel.campo import campo
from modules.law_intel.registro import cargar

#: Conjunto CERRADO. Cada indicador cae en exactamente uno, y el orden es el de la decisión:
#: lo que depende de nosotros primero, lo que no depende de nadie al final.
DE_QUIEN_DEPENDE: Dict[str, str] = {
    "ya_medido": "tiene veredicto: no hay nada que perseguir",
    "trabajo_nuestro": "falta una tarea concreta nuestra y está declarada",
    "decision_del_dueno": "no falta trabajo: falta una decisión de producto",
    "hecho_de_un_tercero": "depende de que un emisor publique, repita o complete algo",
    "lo_impide_la_ley": "la propia redacción del instrumento no admite veredicto",
}

#: Estado del campo → de quién depende. Lo que no está acá se resuelve por regla en
#: `clasificar`, porque depende de algo más que el estado.
_POR_ESTADO = {
    "sin_meta_legal": "lo_impide_la_ley",
    "meta_no_interpretable": "lo_impide_la_ley",
    "pendiente_de_busqueda": "trabajo_nuestro",
    "pendiente_de_derivacion": "trabajo_nuestro",
    "instrumento_discontinuado": "hecho_de_un_tercero",
    "magnitud_no_publicada": "hecho_de_un_tercero",
    "sin_fuente_conocida": "hecho_de_un_tercero",
    "candidato_sin_verificar": "hecho_de_un_tercero",
    # `fuente_no_procesable` y `candidato_descartado` NO están acá a propósito: los dos
    # dependen de si hay una hipótesis declarada, y eso lo decide `clasificar`.
}


def clasificar(expediente_id: str) -> List[Dict[str, Any]]:
    """`[{indicador, nombre, depende_de, motivo, que_haria_falta}]` para los 90 numerados.

    Las dos reglas que no salen del estado del campo:

    * un DESCARTE con hipótesis declarada es trabajo nuestro —la hipótesis dice qué
      comprobar—; sin ella, el candidato se evaluó y midió otra cosa, y reabrirlo depende de
      que aparezca otro emisor;
    * una FUENTE NO PROCESABLE es trabajo nuestro cuando el emisor publica y el problema es
      extraer, que es lo que un extractor resuelve. Se marca así y no como hecho de tercero
      porque el dato existe: lo que falta es ir a buscarlo bien.
    """
    exp = cargar(expediente_id)
    bs = cargar_bindings(expediente_id)
    casillas = campo(expediente_id)
    out: List[Dict[str, Any]] = []
    for ind in exp.numerados:
        b = bs.get(ind.id)
        if b is not None and b.cuenta:
            out.append({"indicador": ind.id, "nombre": ind.nombre,
                        "depende_de": "ya_medido",
                        "motivo": f"verificado por {b.verificado_por}",
                        "que_haria_falta": ""})
            continue
        c = casillas[ind.id]
        hipotesis = (b.hipotesis_sin_comprobar or "").strip() if b else ""
        if c.estado == "candidato_descartado":
            depende = "trabajo_nuestro" if hipotesis else "hecho_de_un_tercero"
            falta = hipotesis or ("que aparezca otro emisor que publique la magnitud: el "
                                  "candidato evaluado mide otra cosa")
        elif c.estado == "fuente_no_procesable":
            depende, falta = "trabajo_nuestro", (
                "construir la extracción: el emisor publica y el problema es el formato")
        else:
            depende = _POR_ESTADO.get(c.estado, "hecho_de_un_tercero")
            falta = c.detalle
        out.append({"indicador": ind.id, "nombre": ind.nombre, "depende_de": depende,
                    "motivo": c.estado, "que_haria_falta": " ".join(falta.split())})
    return out


def resumen(expediente_id: str) -> Dict[str, Any]:
    """La cifra que ordena la decisión, con su composición al lado.

    Se publica el conteo por grupo Y la lista de lo perseguible, porque «quedan 53 sin medir»
    y «7 de esos 53 dependen de nosotros» son la misma realidad y llevan a decisiones
    opuestas.
    """
    filas = clasificar(expediente_id)
    por_grupo: Dict[str, List[str]] = {k: [] for k in DE_QUIEN_DEPENDE}
    for f in filas:
        por_grupo[f["depende_de"]].append(f["indicador"])
    nuestro = por_grupo["trabajo_nuestro"] + por_grupo["decision_del_dueno"]
    return {
        "total": len(filas),
        "por_grupo": {k: len(v) for k, v in por_grupo.items()},
        "indicadores_por_grupo": por_grupo,
        "perseguibles_por_nosotros": sorted(
            nuestro, key=lambda s: [int(p) for p in s.split(".")]),
        "que_significa_cada_grupo": DE_QUIEN_DEPENDE,
        "nota": ("«Perseguible» no promete cobertura: promete que existe una tarea concreta. "
                 "Varias de ellas van a terminar en un motivo definitivo en vez de un "
                 "veredicto, y eso también cierra el indicador."),
    }
