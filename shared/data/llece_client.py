"""LLECE / UNESCO — niveles de desempeño de las pruebas regionales (SERCE · TERCE · ERCE).

**Solo se sirven NIVELES, nunca puntajes, y no es una omisión.** La Ley 1-12 fija sus líneas
base y sus metas de puntaje en la escala de SERCE 2006 (media regional 500); desde TERCE 2013
el LLECE publica con media 700. Un puntaje moderno leído contra una meta de la ley la supera
por unos doscientos puntos sin que el país haya cambiado de desempeño — el ERCE 2019 da 643,95
en lectura de 6to contra una meta de «> 557» para 2030.

Los NIVELES sí son comparables y está documentado en dos fuentes independientes: los de TERCE
son «iguales a los de SERCE 2006» por diseño, y ERCE «mantiene sus puntos de corte fijados en
el estudio anterior, TERCE». Por eso un indicador expresado en porcentaje de alumnos por nivel
sobrevive al cambio de escala y uno expresado en puntaje no.

Exponer aquí el puntaje sería dejar cargada el arma: cualquier consumidor futuro lo ataría a
una meta de la ley y publicaría un cumplimiento falso.

Fuente: tabla oficial del LLECE, `github.com/llece/comparativo`.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Dict, List, Tuple

import httpx

logger = logging.getLogger("sdq.data.llece")

CSV_URL = ("https://raw.githubusercontent.com/llece/comparativo/main/tercevserce.csv")
SOURCE = "LLECE/UNESCO"

#: El archivo se llama `tercevserce` y sus columnas son ERCE vs TERCE. Se mapea el prefijo
#: de columna al AÑO DE APLICACIÓN de cada estudio, que es el período que hay que persistir:
#: rotularlo con el año del archivo o el de publicación fecharía mal la observación.
ESTUDIOS = {"ERCE": "2019", "TERCE": "2013"}

#: País en la tabla. Códigos de dos letras, minúsculas.
PAIS_RD = "do"


class LLECEUnavailable(RuntimeError):
    """No se pudo obtener la tabla. NUNCA se degrada a «no hay dato»."""


def _descargar(timeout: int = 30) -> str:  # pragma: no cover - I/O de red
    try:
        r = httpx.get(CSV_URL, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLECEUnavailable(f"no se pudo descargar la tabla del LLECE ({type(e).__name__}: {e})")
    return r.text


def parse_bajo_nivel_ii(texto: str, materia: str, grado: str,
                        pais: str = PAIS_RD) -> List[Tuple[str, float]]:
    """`[(período, % de alumnos EN O POR DEBAJO del nivel II)]`, ascendente.

    «En o por debajo del nivel II» es la suma de los niveles I y II. Se comprueba que los
    CUATRO niveles sumen 1: si no lo hicieran habría una categoría fuera de la partición y el
    porcentaje estaría midiendo otra cosa. Declarar eso vale más que servir el número.
    """
    filas = [f for f in csv.DictReader(io.StringIO(texto))
             if f.get("pais") == pais and f.get("materia") == materia
             and str(f.get("grado")) == str(grado)]
    if not filas:
        raise LLECEUnavailable(
            f"la tabla no trae {materia} de {grado}º para «{pais}»: no se puede afirmar que "
            f"el dato no exista, solo que esta tabla no lo tiene")
    fila = filas[0]
    out: List[Tuple[str, float]] = []
    for prefijo, periodo in ESTUDIOS.items():
        try:
            niveles = [float(fila[f"{prefijo}_nivel_{i}"]) for i in (1, 2, 3, 4)]
        except (KeyError, TypeError, ValueError):
            continue
        total = sum(niveles)
        if abs(total - 1.0) > 0.005:
            logger.warning("llece: %s %sº %s — los niveles suman %.4f, no 1: se omite",
                           materia, grado, periodo, total)
            continue
        out.append((periodo, round((niveles[0] + niveles[1]) * 100, 2)))
    return sorted(out)


def fetch_bajo_nivel_ii(materia: str, grado: str) -> List[Tuple[str, float]]:  # pragma: no cover
    return parse_bajo_nivel_ii(_descargar(), materia, grado)


def niveles_disponibles(texto: str, pais: str = PAIS_RD) -> Dict[str, List[str]]:
    """Qué materias y grados trae la tabla para un país. Para diagnóstico, no para el sync."""
    out: Dict[str, List[str]] = {}
    for f in csv.DictReader(io.StringIO(texto)):
        if f.get("pais") == pais:
            out.setdefault(str(f.get("materia")), []).append(str(f.get("grado")))
    return out
