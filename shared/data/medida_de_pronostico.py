"""En qué MEDIDA está un número PRONOSTICADO, y cómo se realiza el observado contra él.

**Esta es la misma causa raíz que `shared/data/series_nature.py` cerró un nivel más arriba.**
Allá el defecto era que el emisor declaraba qué mide cada SERIE ("MILLONES DE US$", "%",
"Índice base 2018"), nosotros tirábamos esa declaración al extraer, y cada consumidor tenía
que ADIVINAR qué transformación aplicar. La cura fue capturar la naturaleza, persistirla
junto al dato y que cada consumidor la LEA.

El ledger de pronósticos repetía el defecto un nivel abajo, sobre el PUNTO en vez de sobre la
serie: guardaba un número sin decir en qué medida estaba, y `puntuar_pendientes` suponía que
era directamente comparable con el valor de `target_series`. No lo era. Los dos motores
—nowcast y BVAR— emiten un **Δlog en %** (~0,4) y la serie contra la que se comparaban es el
**índice de volumen** del PIB (~133): el error habría salido ≈ 132,75 y eso se publica como
RMSE en un informe que se vende.

**Las dos declaraciones son distintas y las dos hacen falta.** `MacroSeries.nature` dice qué
mide la SERIE OBSERVADA; `ForecastLog.measure` dice en qué medida está el PUNTO PRONOSTICADO.
Un pronóstico de la variación de un índice es una tasa sobre una serie de nivel: sin las dos,
no hay forma de saber qué restarle a qué.

**La transformación tiene una sola implementación.** Antes de esto había tres copias —
`panel._dlog` (sin ×100, uso interno de la regresión), `bloque._transformar` (×100) y
`backtest.correr` (×100, la única que lo hacía bien)— y el ledger iba a ser la cuarta. Si el
backtest y el track record no realizan el observado igual, miden cosas distintas y nadie se
entera.

**Y vive en `shared/`, no dentro del módulo de macro.** El vocabulario no lo consume solo
quien puntúa: lo necesitan el gate de admisión (`shared/registry/projection.py`) y la prosa
de procedencia (`shared/registry/provenance.py`), que publican el número y su banda. Si la
declaración se quedara en `modules/macro_monitor`, `shared/` tendría que importar de un
módulo —al revés de como este repo declara la dependencia— o cada consumidor volvería a
adivinar la unidad, que es el defecto entero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from shared.data.periodos import mismo_periodo_ano_anterior, periodo_anterior

#: El punto ES el valor de la serie en ese período. Se compara contra el observado tal cual.
LEVEL = "level"
#: El punto es la variación logarítmica contra el período anterior, **en por ciento**
#: (``(ln vₜ − ln vₜ₋₁) × 100``). Es lo que emiten los dos motores del bloque: `bloque`
#: entrega el PIB así y el nowcast multiplica su Δlog por 100 antes de publicarlo.
DLOG_PCT = "dlog_pct"
#: El punto es la variación contra el MISMO período del año anterior, en por ciento
#: (``(vₜ / vₜ₋₄ − 1) × 100`` para una serie trimestral). Es como entra el PIB al bloque del
#: BVAR: el índice que publica el BCRD es la serie ORIGINAL, sin desestacionalizar, y su
#: variación trimestre a trimestre va de −1,13 % a +4,67 % por puro calendario.
YOY_PCT = "yoy_pct"

MEDIDAS: Tuple[str, ...] = (LEVEL, DLOG_PCT, YOY_PCT)

#: Cómo se lee cada medida cuando hay que nombrarla en un texto.
ETIQUETAS: Dict[str, str] = {
    LEVEL: "nivel de la serie",
    DLOG_PCT: "variación logarítmica contra el período anterior, en %",
    YOY_PCT: "variación contra el mismo período del año anterior, en %",
}

#: La coletilla que va PEGADA a un número para que no se lea como otra cosa. Es distinta de
#: `ETIQUETAS` a propósito: una define la medida, la otra acompaña a la cifra, y meterlas en
#: la misma constante obliga a elegir entre una frase que no cierra y una definición que no
#: se puede leer sola.
COMO_SE_LEE: Dict[str, str] = {
    LEVEL: "en el nivel de la serie",
    DLOG_PCT: "en % de variación contra el período anterior",
    YOY_PCT: "en % de variación interanual",
}

#: El sufijo corto para una celda de tabla, donde no entra una frase. Vacío para el nivel:
#: la unidad de un nivel es la de SU serie —un índice, millones de RD$— y este módulo no la
#: conoce. Inventarle un «%» es exactamente el defecto que cerró; la columna lo declara con
#: `COMO_SE_LEE` en su encabezado.
SUFIJO: Dict[str, str] = {
    LEVEL: "",
    DLOG_PCT: "%",
    YOY_PCT: "%",
}


def validar(medida: Optional[str]) -> str:
    """La medida, o un error que nombra las que hay.

    No hay valor por defecto y no lo va a haber: suponer «nivel» para lo que no declaró nada
    es exactamente el defecto que este módulo cierra.
    """
    if medida in MEDIDAS:
        return str(medida)
    raise ValueError(
        f"medida de pronóstico no declarada o desconocida: {medida!r}. Un punto sin medida "
        f"no se puede puntuar contra nada — las declaradas son {', '.join(MEDIDAS)}.")


def periodos_necesarios(medida: str, period: str) -> Tuple[str, ...]:
    """Qué períodos del observado hay que tener para realizar *medida* en *period*.

    Se declara aparte de `realizar` para que quien lee la base pida los dos períodos en UNA
    consulta en vez de descubrir el segundo cuando ya cerró la sesión.
    """
    validar(medida)
    if medida == LEVEL:
        return (period,)
    base = _base_de(medida, period)
    return (period,) if base is None else (base, period)


def _base_de(medida: str, period: str) -> Optional[str]:
    """El período CONTRA EL QUE se mide la variación. Es lo único que distingue a las dos
    medidas de variación, y por eso está en una sola función: con la elección repartida por
    el módulo, una rama toma el trimestre anterior y otra el del año pasado, las dos se
    llaman «la variación del PIB», y restar una de la otra publica una brecha inventada.
    Pasó — ocho actividades salieron contrayéndose en un informe donde el modelo proyectaba
    las dieciocho positivas."""
    return (mismo_periodo_ano_anterior(period) if medida == YOY_PCT
            else periodo_anterior(period))


@dataclass(frozen=True)
class Realizacion:
    """El observado EN LA MEDIDA DEL PUNTO, o el motivo por el que no lo hay.

    `valor` es ``None`` cuando falta algo, nunca 0,0: un cero acá se lee como «el PIB no se
    movió» y produce un error inventado del tamaño del pronóstico.
    """

    valor: Optional[float]
    #: Vacío cuando hay valor. Nombra qué faltó — se publica, no se traga.
    motivo: str = ""


def realizar(medida: str, period: str,
             observado: Mapping[str, Optional[float]]) -> Realizacion:
    """Lo observado en *period*, convertido a la medida en que está el punto.

    *observado* mapea período → valor de la serie de NIVEL (lo que hay en `mm_series`); las
    claves que faltan y los valores nulos son lo mismo para esta función: no llegó el dato.
    """
    validar(medida)
    actual = observado.get(period)
    if actual is None:
        return Realizacion(None, f"sin observado para {period}")
    if medida == LEVEL:
        return Realizacion(float(actual))

    anterior_periodo = _base_de(medida, period)
    if anterior_periodo is None:
        return Realizacion(None, (
            f"«{period}» no resuelve a un período de calendario y una variación necesita "
            "contra qué medirse"))
    anterior = observado.get(anterior_periodo)
    if anterior is None:
        # El período anterior DE CALENDARIO, no «el anterior que haya»: con un hueco, tomar
        # la observación previa disponible computa un cambio de dos períodos y lo rotula de
        # uno. La brecha se declara.
        return Realizacion(None, (
            f"falta el período anterior ({anterior_periodo}) y sin él {period} no tiene "
            "contra qué medirse"))
    if float(anterior) <= 0 or float(actual) <= 0:
        return Realizacion(None, (
            f"un valor no positivo no admite una variación proporcional "
            f"({anterior_periodo}={anterior}, {period}={actual})"))
    if medida == YOY_PCT:
        return Realizacion((float(actual) / float(anterior) - 1.0) * 100.0)
    return Realizacion((math.log(float(actual)) - math.log(float(anterior))) * 100.0)


def serie_realizada(medida: str,
                    observado: Mapping[str, Optional[float]]) -> Dict[str, float]:
    """La serie entera llevada a *medida*. Los períodos que no se pueden realizar NO
    aparecen — no se rellenan."""
    salida: Dict[str, float] = {}
    for period in observado:
        r = realizar(medida, period, observado)
        if r.valor is not None:
            salida[period] = r.valor
    return salida
