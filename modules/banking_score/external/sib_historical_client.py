"""Shim de compatibilidad — este cliente vive ahora en ``shared/data`` (T-VL-0).

Se promovió porque trae balance y resultados completos por entidad, y el eje de valuación los
necesita **sin importar de `modules.banking_score`**: un módulo no importa de otro, y un
valuador atado al motor del score quedaría preso de los cambios de un motor que responde otra
pregunta. Código nuevo importa de ``shared.data.sib_historical_client``.

**Re-exporta; NO reasigna `sys.modules`.** El alias de módulo era tentador —hace que parchar
el shim alcance a la implementación, sin tocar ningún test— pero mypy no lo atraviesa: ve un
módulo que no define nada y marca `attr-defined` en CADA import, 21 errores repartidos por
ocho archivos ajenos. Medido, la alternativa costaba **tres** líneas: los únicos tres sitios
que parchaban el shim ahora parchan el módulo canónico, que es además lo que uno quiere
parchar. Tres líneas contra veintiún errores de tipo en código de otros.

**Los nombres se MIDIERON** leyendo con `ast` qué importa de verdad el repo, no listando lo
que parece público — hay tests que importan privados (acá ninguno, pero salió del mismo barrido). Una lista escrita a mano se
queda corta justo en el símbolo que alguien agregó después.
"""
from shared.data.sib_historical_client import (  # noqa: F401
    FILES,
    SNAPSHOT_DATE,
    download_to_temp,
    load_file,
    logger,
    parse_rows,
    source_file_name,
    sync_all,
)

__all__ = [
    "FILES",
    "SNAPSHOT_DATE",
    "download_to_temp",
    "load_file",
    "logger",
    "parse_rows",
    "source_file_name",
    "sync_all",
]
