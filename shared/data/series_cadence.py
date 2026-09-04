"""Cadencia de una observación — cada cuánto se publica la serie.

Hermano de :mod:`shared.data.series_nature`: la naturaleza dice QUÉ magnitud mide la serie,
la cadencia dice CADA CUÁNTO. Las dos se resuelven en la ingesta y se persisten junto al
dato, para que ningún consumidor tenga que adivinarlas y equivocarse cada uno a su manera.

**Por qué el período manda y la declaración verifica.** El spec de persistencia proponía la
cascada inversa —declaración del registro canónico primero, formato del período como último
recurso «inferido»—. La corrida en seco del 2026-09-03 mostró que no se sostiene:

* La etiqueta del período (``2026-Q1``, ``2026-07``, ``2026``) **no es una inferencia**: la
  fija el parser al normalizar y determina la cadencia sin ambigüedad, fila por fila, con
  cobertura del 100%.
* La declaración del canónico es por SERIE, pero se ingiere por ARCHIVO, y un archivo
  produce muchas series: ``imae_2018.xlsx`` produce doce. Aplicarles a las doce la cadencia
  de la entrada canónica sale bien hoy por casualidad —en los cuatro archivos encendidos
  todas las series comparten cadencia—, y eso no es una regla.
* La declaración del spec de extracción viene vacía en la mitad de los casos (``None`` en
  ``imae_2018.xlsx`` e ``ipc_base_2019-2020.xls``).

Así que la declaración no se usa para RESOLVER sino para DETECTAR: donde lo declarado y lo
derivado discrepan hay un parse equivocado, y eso se registra en vez de resolverse en
silencio eligiendo uno de los dos. Ver :func:`discrepancia_de_cadencia`.

**El vocabulario es inglés, y no es una preferencia.** ``mm_series.frequency`` se sirve por
la Data API que consume PMS, hoy derivándose al leer con una función que devuelve inglés:
persistir español cambiaría el valor de un campo de un contrato vivo. Los otros módulos que
ya pueblan esa columna (``insurance_intel``, ``pension_intel``) escriben inglés. El español
sigue siendo correcto en ``CanonicalSeries.frequency``, que es documentación del registro y
no la columna.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

#: Las tres cadencias que la plataforma persiste, más la respuesta honesta.
ANUAL = "annual"
TRIMESTRAL = "quarterly"
MENSUAL = "monthly"
#: El tipo de cambio se publica DIARIO. Sin esta cadencia el período no tenía día, los ~22
#: días hábiles de un mes colapsaban en `YYYY-MM` y sobrevivía uno arbitrario.
DIARIA = "daily"
DESCONOCIDA = "unknown"

CADENCIAS = (ANUAL, TRIMESTRAL, MENSUAL, DIARIA)

#: Cómo se dice cada una en el registro canónico, que está en español porque es la
#: superficie de documentación. La traducción vive acá —en un solo lugar— y no en cada
#: sitio que compare: tres copias de un mapa de traducción se desincronizan.
DESDE_ESPANOL = {
    "mensual": MENSUAL,
    "trimestral": TRIMESTRAL,
    "anual": ANUAL,
    "diaria": DIARIA,
}

_ANUAL = re.compile(r"\d{4}")
_TRIMESTRAL = re.compile(r"\d{4}-Q[1-4]", re.IGNORECASE)
_MENSUAL = re.compile(r"\d{4}-\d{2}")
_DIARIA = re.compile(r"\d{4}-\d{2}-\d{2}")


def cadencia_de_periodo(period: str) -> str:
    """Cadencia que declara la ETIQUETA del período. ``unknown`` si no la reconoce.

    ``"2025"`` → annual · ``"2025-Q1"`` → quarterly · ``"2025-01"`` → monthly ·
    ``"2025-01-09"`` → daily.
    """
    p = (period or "").strip()
    if _DIARIA.fullmatch(p):
        # Un día que no existe (2026-02-31) no es una cadencia: es un parse roto.
        try:
            date.fromisoformat(p)
        except ValueError:
            return DESCONOCIDA
        return DIARIA
    if _TRIMESTRAL.fullmatch(p):
        return TRIMESTRAL
    if _MENSUAL.fullmatch(p):
        return MENSUAL
    if _ANUAL.fullmatch(p):
        return ANUAL
    return DESCONOCIDA


def normalizar(declarada: Optional[str]) -> Optional[str]:
    """Lleva al vocabulario de la columna una cadencia declarada en cualquiera de los dos
    idiomas. Devuelve ``None`` cuando no hay declaración — que es distinto de ``unknown``:
    «nadie lo declaró» y «lo declaró y no se reconoce» no son lo mismo."""
    if not declarada:
        return None
    d = str(declarada).strip().lower()
    if d in CADENCIAS or d == DESCONOCIDA:
        return d
    return DESDE_ESPANOL.get(d, DESCONOCIDA)


def discrepancia_de_cadencia(declarada: Optional[str], periodos) -> Optional[str]:
    """¿La cadencia declarada contradice la que dicen los períodos? Descripción o ``None``.

    Es la aserción 5 de §4 del spec de persistencia —«ninguna serie trimestral tiene
    períodos con formato mensual»— en forma reutilizable. Una discrepancia significa que el
    parser leyó el eje temporal mal, y eso NO se arregla eligiendo uno de los dos valores:
    se declara, porque la serie entera es sospechosa.
    """
    esperada = normalizar(declarada)
    if esperada is None or esperada == DESCONOCIDA:
        return None
    vistas = {cadencia_de_periodo(str(p)) for p in periodos}
    vistas.discard(DESCONOCIDA)
    # Basta con que la declarada APAREZCA. Un archivo del BCRD suele traer varias hojas con
    # cortes distintos de la misma estadística —`tasa_ocupacion.xls` publica dos anuales y
    # una semestral— y la entrada canónica declara la cadencia de UNA de ellas. Exigir que
    # fuera la única presente marcaba como parse roto lo que es la forma normal del corpus.
    # La señal que importa es la AUSENCIA: si ninguna serie del archivo tiene la cadencia
    # declarada, el eje temporal se leyó mal. Una serie que mezcla formas dentro de sí misma
    # la caza el criterio de formas mezcladas, que es por serie y más filoso que éste.
    if not vistas or esperada in vistas:
        return None
    return (f"declarada {esperada}, pero los períodos dicen "
            f"{', '.join(sorted(vistas))}")
