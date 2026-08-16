"""Las metas se ratifican UNA VEZ y después no se mueven sin una norma que lo autorice.

**Por qué esto es el corazón del producto y no una formalidad.** El hallazgo central del
expediente de la END es el artículo 20: permite al órgano rector —el propio evaluado—
modificar las metas por vía administrativa, sin pasar por el Congreso. Un evaluador cuyo
registro de metas se puede editar sin dejar rastro tiene el mismo defecto que denuncia, y con
menos excusa: nosotros elegimos el diseño.

**El modelo.** El expediente sella el hash de sus metas al ratificarse. A partir de ahí:

  · si las metas coinciden con el sello → `ratificado`, se sirve normal;
  · si difieren y hay una ENMIENDA con base legal que las cubre → `enmendado`, se sirve y el
    informe declara qué norma cambió qué;
  · si difieren y no hay enmienda → `deriva_no_autorizada`, y el expediente NO SE SIRVE.

Ese tercer caso es el que hace que la garantía valga: no alcanza con registrar el cambio si
igual se publica. Un registro que solo avisa es un registro que deriva.

**Tres orígenes de cambio, y no valen lo mismo.** Una reforma por ley y un ajuste
administrativo bajo una potestad delegada son ambos legales y NO son equivalentes: el segundo
es exactamente el mecanismo que el informe señala como falla de diseño. Se registran con
etiquetas distintas para que el informe pueda decirlo.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from modules.law_intel.registro import RAIZ, ExpedienteInvalido, Indicador, cargar

ESTADOS = {
    "ratificado": "las metas coinciden con el sello aprobado",
    "enmendado": "difieren, y una enmienda con base legal cubre exactamente la diferencia",
    "deriva_no_autorizada": "difieren sin norma que lo autorice — el expediente NO se sirve",
    "sin_ratificar": "el expediente todavía no fue aprobado por primera vez",
}

# Jerarquía del acto que autoriza un cambio. No son equivalentes y el informe debe poder
# distinguirlos: `administrativa` es la potestad delegada que el propio análisis señala como
# falla de diseño — legal, pero ejercida por el evaluado sobre su propia vara.
ORIGENES = {
    "ley": "una ley reformó las metas",
    "decreto": "un decreto las modificó dentro de la potestad que la ley le da",
    "administrativa": ("acto del órgano rector bajo una potestad delegada (art. 20 en la END). "
                       "Es legal y es el mecanismo que permite mover la vara sin el Congreso"),
}


class DerivaNoAutorizada(ExpedienteInvalido):
    """Las metas cambiaron y ninguna norma lo autoriza. No se sirve el expediente."""


@dataclass(frozen=True)
class Enmienda:
    id: str
    origen: str
    norma: str
    fecha: str
    indicadores: List[str]
    detalle: str
    hash_resultante: str


@dataclass(frozen=True)
class EstadoRatificacion:
    expediente: str
    estado: str
    hash_actual: str
    hash_sellado: Optional[str] = None
    sellado_el: Optional[str] = None
    sellado_por: Optional[str] = None
    enmienda_vigente: Optional[Enmienda] = None
    indicadores_que_difieren: Optional[List[str]] = None

    @property
    def servible(self) -> bool:
        return self.estado in ("ratificado", "enmendado")


def hash_de_metas(indicadores: List[Indicador]) -> str:
    """Huella de LO QUE LA LEY MANDA, y solo de eso.

    Cubre id, línea base, metas y escala. Deliberadamente NO cubre el nombre del indicador ni
    las notas: corregir una tilde en un rótulo no es mover una meta, y si lo tratáramos igual
    el sello se rompería por ruido y la gente aprendería a re-sellar sin mirar.
    """
    material = [
        {"id": i.id, "escala": i.escala, "base": i.base_valor,
         "metas": {a: v for a, v in sorted(i.metas.items())}}
        for i in sorted(indicadores, key=lambda x: x.id)
    ]
    crudo = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def _cargar_sello(expediente_id: str) -> Dict[str, Any]:
    import yaml  # type: ignore[import-untyped]

    ruta = RAIZ / expediente_id.replace("/", "") / "sello.yaml"
    if not ruta.exists():
        return {}
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=8)
def estado(expediente_id: str) -> EstadoRatificacion:
    exp = cargar(expediente_id)
    actual = hash_de_metas(exp.indicadores)
    doc = _cargar_sello(expediente_id)
    sello = doc.get("sello") or {}
    sellado = sello.get("hash_metas")

    if not sellado:
        return EstadoRatificacion(expediente_id, "sin_ratificar", actual)
    if sellado == actual:
        return EstadoRatificacion(expediente_id, "ratificado", actual, sellado,
                                  sello.get("fecha"), sello.get("aprobado_por"))

    # Difieren: solo una enmienda cuyo hash resultante sea EXACTAMENTE el actual lo autoriza.
    # Exigir el hash y no solo la existencia de la enmienda impide que una norma real sirva
    # de paraguas para un cambio distinto del que autorizó.
    for e in reversed(doc.get("enmiendas") or []):
        enm = Enmienda(**e)
        if enm.hash_resultante == actual:
            return EstadoRatificacion(expediente_id, "enmendado", actual, sellado,
                                      sello.get("fecha"), sello.get("aprobado_por"),
                                      enmienda_vigente=enm)
    return EstadoRatificacion(expediente_id, "deriva_no_autorizada", actual, sellado,
                              sello.get("fecha"), sello.get("aprobado_por"))


def exigir_servible(expediente_id: str) -> EstadoRatificacion:
    """Puerta de servicio. Un expediente derivado NO se publica.

    Un registro que solo avisa de la deriva es un registro que deriva.
    """
    st = estado(expediente_id)
    if st.estado == "deriva_no_autorizada":
        raise DerivaNoAutorizada(
            f"Las metas de '{expediente_id}' difieren del sello ratificado y ninguna enmienda "
            f"con base legal lo autoriza. Hash sellado {st.hash_sellado[:12] if st.hash_sellado else '—'}, "
            f"hash actual {st.hash_actual[:12]}. Para cambiarlas hace falta la norma que lo "
            f"autorice, registrada como enmienda.")
    return st


def publicable(expediente_id: str) -> Dict[str, Any]:
    """Cómo se dice el estado de ratificación en un informe."""
    st = estado(expediente_id)
    if st.estado == "enmendado" and st.enmienda_vigente:
        e = st.enmienda_vigente
        return {
            "estado": st.estado,
            "frase": (f"Las metas de este instrumento fueron modificadas por {e.norma} "
                      f"({e.fecha}) respecto de las ratificadas originalmente. "
                      f"Alcance: {e.detalle}"),
            "origen": e.origen, "origen_nota": ORIGENES.get(e.origen),
            "indicadores_afectados": e.indicadores,
            # La advertencia solo aparece cuando corresponde: un cambio administrativo es el
            # mecanismo que permite mover la vara sin el Congreso, y el informe lo señala.
            "advertencia": (("El cambio se hizo por acto del propio órgano evaluado bajo una "
                             "potestad delegada, no por ley. La comparación contra las metas "
                             "originales sigue siendo legítima y se ofrece.")
                            if e.origen == "administrativa" else None),
        }
    return {"estado": st.estado, "frase": ESTADOS[st.estado], "origen": None,
            "origen_nota": None, "indicadores_afectados": [], "advertencia": None}
