"""De dónde salen las observaciones de una variable, para todo el módulo.

Vivía dentro del router y desde ahí solo lo alcanzaba la verificación: el contexto del
informe pasaba un diccionario vacío, así que con cuatro bindings ya verificados el semáforo
seguía respondiendo `sin_dato`. Promover un binding y no conectar su serie deja el informe
diciendo «mide 4 de 90» y después «sin dato» en los cuatro.

El proveedor lee el **Data Registry**, no una tabla: el dato de la plataforma vive repartido
por módulo. El código de una serie es `<eje>:<variable>`, con el eje adelante porque las
claves no son únicas entre ejes.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

Observacion = Tuple[str, float]
Proveedor = Callable[[str], Sequence[Observacion]]


def proveedor_registro(db: Optional[Session]) -> Proveedor:
    """Lee el registro una vez y sirve `[(período, valor)]` por código de serie.

    Un punto por variable, no una serie: el registro publica el valor vigente del eje y su
    período. Alcanza para verificar existencia y para decir la distancia a la meta; NO
    alcanza para trayectoria, y el semáforo ya se niega a emitir tendencia con una sola
    observación en vez de inventar una pendiente.
    """
    from shared.registry.service import build_data_registry

    reg = build_data_registry(db)
    por_clave: Dict[str, List[Observacion]] = {}
    for eje in getattr(reg, "axes", ()) or ():
        periodo = getattr(eje, "period", None)
        if not periodo:
            continue
        for sig in getattr(eje, "signals", ()) or ():
            if sig.value is None:
                continue
            por_clave[f"{eje.sector_key}:{sig.key}"] = [(str(periodo), float(sig.value))]

    def leer(codigo: str) -> List[Observacion]:
        return por_clave.get(codigo, [])
    return leer


def series_de(bindings, proveedor: Proveedor) -> Dict[str, List[Observacion]]:
    """`{código de serie: observaciones}` para los bindings que CUENTAN.

    Solo los verificados: servirle al semáforo la serie de un binding propuesto lo haría
    emitir un veredicto sobre una hipótesis, que es justo lo que el estado existe para evitar.
    """
    out: Dict[str, List[Observacion]] = {}
    for b in bindings.values():
        if b.cuenta and b.serie not in out:
            out[b.serie] = list(proveedor(b.serie))
    return out
