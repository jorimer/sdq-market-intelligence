"""Shim de compatibilidad — este cliente vive ahora en ``shared/data`` (T-VL-0).

Se promovió porque trae balance y resultados completos por entidad, y el eje de valuación los
necesita **sin importar de `modules.banking_score`**: un módulo no importa de otro, y un
valuador atado al motor del score quedaría preso de los cambios de un motor que responde otra
pregunta. Código nuevo importa de ``shared.data.sib_data_client``.

**Re-exporta; NO reasigna `sys.modules`.** El alias de módulo era tentador —hace que parchar
el shim alcance a la implementación, sin tocar ningún test— pero mypy no lo atraviesa: ve un
módulo que no define nada y marca `attr-defined` en CADA import, 21 errores repartidos por
ocho archivos ajenos. Medido, la alternativa costaba **tres** líneas: los únicos tres sitios
que parchaban el shim ahora parchan el módulo canónico, que es además lo que uno quiere
parchar. Tres líneas contra veintiún errores de tipo en código de otros.

**Los nombres se MIDIERON** leyendo con `ast` qué importa de verdad el repo, no listando lo
que parece público — hay tests que importan privados (`_norm` y `_celdas_serializadas`). Una lista escrita a mano se
queda corta justo en el símbolo que alguien agregó después.
"""
from shared.data.sib_data_client import (  # noqa: F401
    CAMBIARIA_DISPLAY_NAMES,
    EIC_TIPOS,
    SIBDataClient,
    SIB_ENTITY_CODES,
    _celdas_serializadas,
    _norm,
    cambiaria_display_name,
    get_sib_data_client,
    logger,
)

__all__ = [
    "CAMBIARIA_DISPLAY_NAMES",
    "EIC_TIPOS",
    "SIBDataClient",
    "SIB_ENTITY_CODES",
    "_celdas_serializadas",
    "_norm",
    "cambiaria_display_name",
    "get_sib_data_client",
    "logger",
]
