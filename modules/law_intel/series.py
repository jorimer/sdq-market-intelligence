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

import logging

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from shared.registry.signals import NATIONAL

logger = logging.getLogger("sdq.law_intel.series")

Observacion = Tuple[str, float]
Proveedor = Callable[[str], Sequence[Observacion]]


def proveedor_registro(db: Optional[Session]) -> Proveedor:
    """Lee el registro una vez y sirve `[(período, valor)]` por código de serie.

    Sirve la SERIE completa para las señales que la traen (``history``) y un punto suelto
    para las que no. La distinción no se disimula: con una observación el semáforo se niega
    a emitir tendencia en vez de inventar una pendiente, y ese sigue siendo el estado
    verdadero de las variables que el registro publica como foto —hoy, las que vienen del
    panel del IDM, que se arma con un solo período—.
    """
    from shared.registry.service import build_data_registry

    reg = build_data_registry(db)
    por_clave: Dict[str, List[Observacion]] = {}
    omitidas: List[str] = []
    for eje in getattr(reg, "axes", ()) or ():
        periodo_eje = getattr(eje, "period", None)
        for sig in getattr(eje, "signals", ()) or ():
            if sig.value is None:
                continue
            # El período de la SEÑAL manda sobre el del eje. No todas las variables de un
            # eje se actualizan a la vez: la razón de ocupación femenina/masculina traía
            # 2025 mientras el eje social iba por 2024, y estampar el del eje servía el
            # valor de un año con el rótulo de otro. En un informe que juzga contra la meta
            # de un año concreto eso no es metadato: es la cifra equivocada.
            # ⛔ Solo señales de alcance NACIONAL. TODO indicador de una ley nacional fija
            # una meta para el país; una variable medida por sujeto publica el valor de UN
            # sujeto —el registro sirve el de la primera región del panel— y compararlo
            # contra la meta del país es comparar cosas distintas. Pasó de verdad: la
            # pobreza extrema de cibao_norte (2,0%) se publicó como cifra nacional y con
            # ella «la meta de 2030, alcanzada seis años antes».
            #
            # Se rechaza en vez de promediar: el promedio simple de diez regiones no es la
            # cifra del país (habría que ponderar por población) y fabricarlo sería
            # inventar el dato que falta en lugar de declararlo.
            if getattr(sig, "scope", NATIONAL) != NATIONAL:
                omitidas.append(f"{eje.sector_key}:{sig.key}")
                continue
            # La SERIE completa cuando el eje la sirve; el punto suelto si no. Con una
            # sola observación el semáforo se niega —bien— a emitir tendencia, así que sin
            # historia los veredictos «retrocede» y «no alcanzará» no existían para ningún
            # indicador: solo sabíamos decir nivel, y la ley pide juzgar AVANCE.
            historia = getattr(sig, "history", ()) or ()
            if historia:
                por_clave[f"{eje.sector_key}:{sig.key}"] = [
                    (str(p), float(v)) for p, v in historia]
                continue
            periodo = getattr(sig, "period", None) or periodo_eje
            if not periodo:
                continue
            por_clave[f"{eje.sector_key}:{sig.key}"] = [(str(periodo), float(sig.value))]

    if omitidas:
        logger.info("law: %d señales omitidas por no ser nacionales (%s)",
                    len(omitidas), ", ".join(sorted(omitidas)[:8]))

    def leer(codigo: str) -> List[Observacion]:
        return por_clave.get(codigo, [])
    return leer


def series_de(bindings, proveedor: Proveedor) -> Dict[str, Sequence[Observacion]]:
    """`{código de serie: observaciones}` para los bindings que CUENTAN.

    Solo los verificados: servirle al semáforo la serie de un binding propuesto lo haría
    emitir un veredicto sobre una hipótesis, que es justo lo que el estado existe para evitar.
    """
    # `Sequence` y no `List` en el retorno: `Dict` es INVARIANTE en su valor, así que
    # prometer la lista concreta impide pasarle el resultado a `panel()`, que pide la
    # secuencia. La lista es un detalle de cómo se arma, no del contrato.
    out: Dict[str, Sequence[Observacion]] = {}
    for b in bindings.values():
        if b.cuenta and b.serie not in out:
            out[b.serie] = list(proveedor(b.serie))
    return out
