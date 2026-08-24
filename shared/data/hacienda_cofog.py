"""Clasificación funcional del gasto del Gobierno Central (COFOG) — Ministerio de Hacienda.

Es la fuente del indicador **2.33 de la END** y es mejor que la que teníamos: una sola hoja
de cálculo con la serie **2008-2025**, anual, con el monto y con **el % del PIB que el propio
emisor computa**. Lo que había antes —leer el cuadro funcional de trece PDF de DIGEPRES, de
hasta 980 páginas— sigue sirviendo, pero como CONTRASTE, no como vía principal.

**Las dos series se cruzaron el 2026-08-24 y coinciden.** En nueve de los once años en que
las dos existen, la diferencia es menor al 1,5%: 2009 0,2% · 2012 1,4% · 2019 0,6% ·
2022 0,3%. Son dos lecturas independientes, de dos documentos distintos del mismo Estado, y
que cierren entre sí es la comprobación más fuerte que este indicador va a tener.

**Y cubre los años que a DIGEPRES le faltaban, que son METAS de la ley**: 2020 y 2025. El
cuadro funcional no aparece en ningún informe de DIGEPRES de esos ejercicios.

Dos salvedades que viajan con el dato porque cambian lo que se puede afirmar:

* **Los años marcados con asterisco son PRELIMINARES** —2021 en adelante al momento de
  escribir esto— y el archivo lo declara al pie. No es un detalle de forma: la revisión al
  alza de estas cifras es justamente lo que explica que el %PIB que publicaba DIGEPRES en sus
  informes quedara 6-8% por encima del que se computa hoy con el PIB revisado.
* **El cuadro mide EROGACIÓN**, que el propio archivo define como gasto más inversión bruta
  en activos no financieros. La ley dice «gasto». Las dos magnitudes coinciden dentro del 1,5%
  contra la lectura de DIGEPRES, así que la diferencia no manda sobre ningún veredicto, pero
  el que compare contra otra fuente tiene que saberlo.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sdq.data.hacienda_cofog")

SOURCE = "Ministerio de Hacienda"
LICENSE = "datos públicos Ministerio de Hacienda (Estadísticas Fiscales) — uso con cita"

#: La serie histórica COFOG del Gobierno Central Presupuestario. La ruta lleva `2015/04` por
#: la fecha de la PRIMERA publicación, no la de la última: el emisor reescribe el mismo
#: archivo cada año. Comprobado el 2026-08-24: responde 200 y llega hasta 2025.
URL = ("https://www.hacienda.gob.do/wp-content/uploads/2015/04/"
       "Serie-historica-COFOG-Gobierno-Central-Presupuestario-Anual-y-Trimestral-2.xlsx")

#: Las dos hojas anuales que se leen. La del %PIB trae la razón ya computada por el emisor;
#: la de montos existe para poder recomputarla y para que el monto viaje con la razón.
HOJA_PCT_PIB = "Anual % PIB"
HOJA_MONTO = "Anual $RD"

#: El universo que la ley fija, y que el encabezado de la hoja tiene que DECLARAR. El mismo
#: emisor publica otros agregados fiscales; leer el equivocado no rompe nada, cambia el sujeto.
UNIVERSO = "GOBIERNO CENTRAL PRESUPUESTARIO"

#: El código COFOG de Salud. Se exige el código Y la palabra: «Salud» sola aparece también en
#: subfunciones (`7.0.7.1 Productos médicos`) que miden una parte, no el total.
CODIGO_SALUD = "7.0.7"

#: La hoja guarda el %PIB como FRACCIÓN (0,0136 = 1,36%). Multiplicar por cien es obligatorio
#: y por eso está acá y no incrustado: si el emisor cambiara a porcentaje, el guard de banda
#: lo atrapa y este es el único lugar donde se corrige.
FACTOR_A_PORCENTAJE = 100.0

#: Banda de plausibilidad de la razón. El gasto público en salud de un país cabe holgado; lo
#: que queda fuera es un error de escala o de fila, no un país.
BANDA_PCT_PIB = (0.3, 12.0)

_TIMEOUT = 180.0


class CofogError(RuntimeError):
    """No se pudo leer la serie. NUNCA se degrada a «no hay dato»."""


@dataclass(frozen=True)
class GastoFuncional:
    """Un año de la serie, con lo que hace falta para saber qué se puede afirmar de él."""

    anio: int
    pct_pib: float
    monto_mm_rd: Optional[float] = None
    #: El emisor marca con asterisco los años cuya cifra todavía puede moverse. Viaja porque
    #: «preliminar» y «definitivo» no sostienen la misma afirmación.
    preliminar: bool = False


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t if t is not None else ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def anio_de(celda: object) -> Optional[int]:
    """El año de una celda de encabezado, o `None`.

    El emisor escribe `2008.0` para los cerrados y `2021*` para los preliminares — números y
    texto en la misma fila. Devolver `None` en vez de levantar es correcto acá: la fila trae
    también la etiqueta de la columna de rótulos, que no es un año.
    """
    t = str(celda).strip().replace("*", "")
    if t.endswith(".0"):
        t = t[:-2]
    return int(t) if re.fullmatch(r"(?:19|20)\d\d", t) else None


def es_preliminar(celda: object) -> bool:
    return "*" in str(celda)


def fila_de_salud(primera_columna: List[Any]) -> Optional[int]:
    """Índice de la fila de Salud, exigiendo el CÓDIGO y no solo la palabra.

    `7.0.7.1 Productos médicos` también dice «Salud» en su rama y mide una parte del total.
    Confundirlas no rompe nada: publica otra magnitud contra la meta de la ley.
    """
    objetivo = f"{CODIGO_SALUD} SALUD"
    for i, celda in enumerate(primera_columna):
        if _norm(celda) == objetivo:
            return i
    return None


def verificar(pct: float, anio: int) -> None:
    if not (BANDA_PCT_PIB[0] <= pct <= BANDA_PCT_PIB[1]):
        raise CofogError(
            f"{anio}: {pct:.3f}% del PIB queda fuera de la banda {BANDA_PCT_PIB}. La hoja "
            f"guarda la razón como FRACCIÓN, así que esto es un error de escala o de fila.")


def leer_hojas(hoja_pct: List[List[Any]],
               hoja_monto: Optional[List[List[Any]]] = None) -> List[GastoFuncional]:
    """La serie de Salud a partir de las hojas ya leídas como listas de filas.

    Se separa de la descarga para que los tests corran sobre las filas REALES del emisor sin
    depender de la red ni de un motor de hojas de cálculo.
    """
    # El SUJETO se exige de la hoja entera; la fila de AÑOS se busca aparte. Son dos
    # comprobaciones distintas y juntarlas fue un defecto: tres filas de esta hoja nombran el
    # universo —el título, el subtítulo y el encabezado— y quedarse con «la primera que
    # coincide» devolvía el título, que no trae ningún año. Es el mismo error que tomar la
    # primera columna «%PIB» de un cuadro que trae dos.
    if not any(UNIVERSO in _norm(f[0] if f else "") for f in hoja_pct):
        raise CofogError(
            f"ninguna fila declara «{UNIVERSO}»: o no es la hoja anual, o el emisor cambió "
            f"el universo que publica — y ahí el dato mide otro sujeto.")
    encabezado = max(hoja_pct, key=lambda f: sum(anio_de(c) is not None for c in f))
    if sum(anio_de(c) is not None for c in encabezado) < 5:
        raise CofogError(
            "ninguna fila de la hoja trae una serie de años: el emisor cambió la forma del "
            "encabezado y leer por posición serviría la columna equivocada.")

    primera = [f[0] if f else None for f in hoja_pct]
    i = fila_de_salud(primera)
    if i is None:
        raise CofogError(
            f"la hoja no trae una fila «{CODIGO_SALUD} Salud». O cambió el clasificador, o "
            f"se está leyendo la hoja equivocada.")

    montos: Dict[int, float] = {}
    if hoja_monto:
        cab_m = max(hoja_monto, key=lambda f: sum(anio_de(c) is not None for c in f))
        prim_m = [f[0] if f else None for f in hoja_monto]
        j = fila_de_salud(prim_m)
        if j is not None:
            for c, celda in enumerate(cab_m):
                a = anio_de(celda)
                if a is not None and c < len(hoja_monto[j]):
                    v = hoja_monto[j][c]
                    if isinstance(v, (int, float)):
                        montos[a] = float(v)

    out: List[GastoFuncional] = []
    for c, celda in enumerate(encabezado):
        a = anio_de(celda)
        if a is None or c >= len(hoja_pct[i]):
            continue
        v = hoja_pct[i][c]
        if not isinstance(v, (int, float)):
            continue
        pct = round(float(v) * FACTOR_A_PORCENTAJE, 3)
        verificar(pct, a)
        out.append(GastoFuncional(anio=a, pct_pib=pct, monto_mm_rd=montos.get(a),
                                  preliminar=es_preliminar(celda)))
    if not out:
        raise CofogError("la fila de Salud no trae ningún año legible")
    return sorted(out, key=lambda g: g.anio)


def fetch() -> List[GastoFuncional]:  # pragma: no cover - red + hoja de cálculo
    """Descarga la serie histórica y devuelve la línea de Salud, año por año."""
    import io

    import httpx
    import pandas as pd

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": "sdq-mip/1.0"}) as c:
        r = c.get(URL)
        r.raise_for_status()
        contenido = r.content

    def _filas(hoja: str) -> List[List[Any]]:
        df = pd.read_excel(io.BytesIO(contenido), sheet_name=hoja, header=None)
        return [list(df.iloc[k]) for k in range(len(df))]

    try:
        serie = leer_hojas(_filas(HOJA_PCT_PIB), _filas(HOJA_MONTO))
    except ValueError as e:  # hoja inexistente → el emisor renombró
        raise CofogError(
            f"no se pudo abrir «{HOJA_PCT_PIB}»/«{HOJA_MONTO}»: {e}. El emisor renombró las "
            f"hojas y leer la que quede a mano serviría otra magnitud.") from e
    logger.info("[cofog] Salud %d-%d (%d años, %d preliminares)",
                serie[0].anio, serie[-1].anio, len(serie),
                sum(1 for g in serie if g.preliminar))
    return serie
