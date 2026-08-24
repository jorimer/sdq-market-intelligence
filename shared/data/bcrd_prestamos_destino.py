"""Préstamos por destino económico (BCRD) — indicador 3.24 de la END.

El banco central publica el stock de préstamos por destino, mensual desde 1996, en tres
PERÍMETROS dentro del mismo archivo: las Otras Sociedades de Depósito consolidadas, los
**Bancos Múltiples** solos, y el resto de las OSD. Cuál se lee cambia el resultado, y el
propio evaluado declaró cuál corresponde: el 5to Informe de Avance de la END (enero 2018,
nota al pie 2, p. 35) dice que la línea base del artículo 26 «corresponde al crédito de la
**banca múltiple a la producción de bienes y servicios** / PIB».

**Este módulo existe porque el motivo de descarte del 3.24 no se podía rehacer.** El
expediente citaba ocho cifras de un barrido que no dejó conector, ni serie persistida, ni
script — solo las conclusiones transcritas. Un motivo que nadie puede recomputar no es
evidencia, y por eso el motivo quedó suspendido hasta que existiera este camino.

**La convención se declara antes de mirar el resultado**, que es la única forma de que un
promedio de ventana no se convierta en una búsqueda del número que conviene: stock de
DICIEMBRE de cada año sobre el PIB nominal de ese año, y la ventana de la ley —«promedio
2005-2010»— se promedia COMPLETA. Es la misma convención con la que se midió el 2.36.
"""
from __future__ import annotations

import datetime as dt
import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.bcrd_prestamos")

SOURCE = "BCRD — Estadísticas Monetarias y Financieras Armonizadas"
LICENSE = "estadísticas públicas del Banco Central de la República Dominicana — uso con cita"

URL = ("https://cdn.bancentral.gov.do/documents/estadisticas/sector-monetario-y-financiero/"
       "documents/serie_prestamos_por_destino_armonizados.xlsx")

#: Los tres perímetros que conviven en la hoja, por el texto que los titula. **Cuál se lee
#: cambia el resultado**, así que se nombra y no se toma el primero: el consolidado incluye
#: cooperativas, corporaciones de crédito y entidades financieras públicas además de la banca
#: múltiple.
PERIMETROS = {
    "consolidado": "OTRAS SOCIEDADES DE DEPOSITOS (CONSOLIDADO)",
    "banca_multiple": "(BANCOS MULTIPLES)",
    "resto_osd": "(RESTO DE LAS OSD)",
}

#: El perímetro que el evaluado DECLARA para la línea base del 3.24.
PERIMETRO_DEL_324 = "banca_multiple"

#: La fila que agrega moneda nacional y extranjera. Las otras dos —M/N y M/E— son sus partes,
#: y sumar las tres contaría cada préstamo dos veces.
FILA_CONSOLIDADA = "SECTOR PRIVADO (CONSOLIDADO)"

#: Destinos que son PRODUCCIÓN de bienes. No incluye comercio ni servicios: es el subconjunto
#: más angosto defendible, y se nombra aparte porque es el que más se acerca a la línea base.
DESTINOS_BIENES = ("AGRICULTURA", "EXPLOTACION DE MINAS", "INDUSTRIAS MANUFACTURERAS",
                   "ELECTRICIDAD", "CONSTRUCCION")

#: Destinos que NO son producción por ninguna lectura: consumo, vivienda y el residual.
DESTINOS_NO_PRODUCTIVOS = ("ADQUISICION DE VIVIENDAS", "PRESTAMOS DE CONSUMO",
                           "TARJETAS DE CREDITO", "OTROS PRESTAMOS DE CONSUMO",
                           "RESTO DE OTRAS ACTIVIDADES")

_TIMEOUT = 300.0


class PrestamosError(RuntimeError):
    """No se pudo leer el cuadro. NUNCA se degrada a «no hay dato»."""


@dataclass(frozen=True)
class Bloque:
    """Un perímetro de la hoja: dónde empieza, y qué filas de destino tiene."""

    perimetro: str
    fila_encabezado: int
    fila_consolidada: int
    destinos: Dict[str, int]


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t if t is not None else ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _num(v: object) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else 0.0


def bloques_de(filas: Sequence[Sequence[Any]]) -> Dict[str, Bloque]:
    """Los tres perímetros de la hoja, ubicados por su TÍTULO y no por su posición.

    El archivo apila los tres bloques con la misma estructura interna; leer por índice fijo
    serviría el consolidado creyendo leer la banca múltiple, que es una diferencia de casi el
    doble en el agregado privado.
    """
    titulos: List[Tuple[int, str]] = []
    for i, f in enumerate(filas):
        for celda in f:
            if not isinstance(celda, str) or len(celda) < 20:
                continue
            n = _norm(celda)
            for clave, marca in PERIMETROS.items():
                if marca in n:
                    titulos.append((i, clave))
                    break
    out: Dict[str, Bloque] = {}
    for k, (inicio, clave) in enumerate(titulos):
        fin = titulos[k + 1][0] if k + 1 < len(titulos) else len(filas)
        encabezado = next((i for i in range(inicio, fin)
                           if any(isinstance(c, (dt.datetime,)) or type(c).__name__ == "Timestamp"
                                  for c in filas[i])), None)
        consolidada = next((i for i in range(inicio, fin)
                            if filas[i] and _norm(filas[i][0]) == FILA_CONSOLIDADA), None)
        if encabezado is None or consolidada is None:
            continue
        destinos: Dict[str, int] = {}
        for i in range(consolidada + 1, fin):
            r = _norm(filas[i][0] if filas[i] else "")
            if not r or r == FILA_CONSOLIDADA or r.startswith("EN MILLONES"):
                break
            destinos[r] = i
        out[clave] = Bloque(clave, encabezado, consolidada, destinos)
    faltan = sorted(set(PERIMETROS) - set(out))
    if faltan:
        raise PrestamosError(
            f"la hoja no trae los perímetros {faltan}: el emisor cambió cómo los titula, y "
            f"leer el que quede serviría otro universo de entidades")
    return out


def columnas_de_diciembre(encabezado: Sequence[Any]) -> Dict[int, int]:
    """`{año: columna}` de los cierres de diciembre.

    Solo diciembre, y no es comodidad: el stock de un mes intermedio contra el PIB del año
    entero mezcla un corte con un flujo anual.
    """
    out: Dict[int, int] = {}
    for c, v in enumerate(encabezado):
        fecha = v if isinstance(v, dt.datetime) else None
        if fecha is None and type(v).__name__ == "Timestamp":
            fecha = v.to_pydatetime()
        if fecha is not None and fecha.month == 12:
            out[fecha.year] = c
    return out


def es_productivo(destino: str) -> bool:
    """Si un destino cuenta como producción de bienes Y servicios.

    Se define por EXCLUSIÓN —todo menos consumo, vivienda y el residual— porque la ley dice
    «producción de bienes y servicios» y el comercio, la hostelería y el transporte son
    servicios. La lectura angosta, solo bienes, vive en `DESTINOS_BIENES`.
    """
    n = _norm(destino)
    return not any(m in n for m in DESTINOS_NO_PRODUCTIVOS)


def monto(filas: Sequence[Sequence[Any]], bloque: Bloque, columna: int,
          destinos: Optional[Sequence[str]] = None) -> float:
    """Millones de RD$ de un perímetro y un conjunto de destinos, en una columna.

    Sin `destinos` suma los PRODUCTIVOS. Nunca suma la fila consolidada junto con sus
    destinos: sería contar cada préstamo dos veces.
    """
    if destinos is None:
        elegidos = [i for r, i in bloque.destinos.items() if es_productivo(r)]
    else:
        marcas = tuple(_norm(d) for d in destinos)
        elegidos = [i for r, i in bloque.destinos.items()
                    if any(m in r for m in marcas)]
    if not elegidos:
        raise PrestamosError(
            f"ningún destino del perímetro «{bloque.perimetro}» coincide con {destinos}: "
            f"el emisor renombró las actividades")
    return sum(_num(filas[i][columna]) for i in elegidos)


def razon_de_ventana(filas: Sequence[Sequence[Any]], bloque: Bloque,
                     pib_nominal_mm: Dict[int, float], anios: Sequence[int],
                     destinos: Optional[Sequence[str]] = None) -> float:
    """El promedio de la ventana, en % del PIB. La ventana se promedia COMPLETA.

    Si falta un año la ventana no es la que la ley nombra, y promediar los que hay produciría
    un número que se parece al pedido sin serlo. Ahí se levanta.
    """
    dic = columnas_de_diciembre(filas[bloque.fila_encabezado])
    faltan = [a for a in anios if a not in dic or a not in pib_nominal_mm]
    if faltan:
        raise PrestamosError(
            f"la ventana {anios[0]}-{anios[-1]} está incompleta: faltan {faltan}. Promediar "
            f"los años que hay daría un número parecido al que pide la ley sin serlo.")
    pcts = [monto(filas, bloque, dic[a], destinos) / pib_nominal_mm[a] * 100.0 for a in anios]
    return round(sum(pcts) / len(pcts), 3)


def fetch_filas() -> List[List[Any]]:  # pragma: no cover - red
    """Las filas de la hoja del emisor."""
    import io

    import httpx
    import pandas as pd

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": "sdq-mip/1.0"}) as c:
        r = c.get(URL)
        r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=None)
    return [list(df.iloc[k]) for k in range(len(df))]
