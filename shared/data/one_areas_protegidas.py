"""Áreas protegidas de República Dominicana (ONE) — indicador 4.2 de la END.

La Oficina Nacional de Estadística publica la superficie protegida por categoría, separando
**terrestre y marina**, de 2007 a 2024. El indicador de la ley es una razón —«% del área
total»— que el conjunto NO trae: hay que computarla, y el denominador es el área terrestre
del país, que viene de su propia fuente y no escrita a mano acá.

**Qué se suma, y por qué no es «todas las filas».** El cuadro tiene diecinueve filas por año
en dos niveles: seis GRUPOS de categoría y, debajo de cada uno, sus subcategorías. Sumarlas
todas cuenta cada superficie dos veces y da casi el doble. Se suman los seis grupos.

**Y cuáles son los grupos no se decide por su rótulo.** «Monumentos Naturales» es a la vez
grupo y subcategoría —una de las dos lleva un espacio al final— y «Refugios de Vida
Silvestre» aparece bajo dos grupos distintos. Normalizar los rótulos las vuelve
indistinguibles. Lo que sí es estable son las POSICIONES: las catorce ediciones traen las
mismas diecinueve filas en el mismo orden, y eso se comprueba contra `ESTRUCTURA` antes de
leer nada. Es posición con guard, que es distinto de leer por posición y confiar.

**El emisor no siempre cuadra consigo mismo, y eso se DECLARA en vez de tirar el año.** En
2012, 2014 y 2015 la superficie marina del grupo de protección estricta no es la suma de sus
subcategorías; en 2021 y 2022 pasa con la terrestre de dos grupos. Un primer intento de
identificar los grupos POR esa identidad se saltaba en silencio los que no cerraban y
producía una serie con años rotos —2021 daba 3.037 km² donde van 11.896—, que es exactamente
el modo de falla que este repositorio persigue: no romperse, servir algo plausible.

**La razón es TERRESTRE sobre área terrestre, y lo dice el oráculo.** El informe de avance
del propio Estado dice que el indicador «se actualizó tomando en consideración las
desagregaciones de superficie terrestre y superficie marina», lo que deja abierto si la razón
incluye lo marino. Con lo terrestre sobre el área del país, 2009 da 24,19% contra los 24,4
que fija la ley — Δ 0,9%. Metiendo lo marino sobre el área terrestre más la zona económica
exclusiva da 3,7%. No hay que opinar: una reproduce la línea base y la otra no.
"""
from __future__ import annotations

import csv
import io
import logging
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.one_areas_protegidas")

SOURCE = "ONE"
LICENSE = ("datos.gob.do — Open Database License (ODbL) v1.0, declarada POR DATASET en el "
           "portal: exige el aviso de atribución, y el share-alike alcanza a las bases "
           "DERIVADAS. Un informe o un gráfico es «Produced Work» y NO lo dispara (§4.5) — "
           "https://opendatacommons.org/licenses/odbl/1-0/")

URL = ("https://descargas.one.gob.do/download/OGTIC/"
       "Areas_Protegidas_en_Republica_Dominicana_2007-2024.csv")

#: El emisor sirve el archivo en latin-1. Leerlo como UTF-8 revienta en la primera tilde.
ENCODING = "latin-1"
SEPARADOR = ";"

#: El código del área terrestre del país en el catálogo del republicador. Es el denominador,
#: y viene de una fuente en vez de estar escrito acá: un área nacional a mano envejece cuando
#: el emisor la revisa, y nadie se entera.
CODIGO_AREA_TERRESTRE = "AG.LND.TOTL.K2"

#: Las diecinueve filas, en su orden, normalizadas. Es el guard que permite leer por posición:
#: si el emisor agrega, quita o reordena una categoría, esto deja de coincidir y se levanta —
#: en vez de sumar la fila de al lado y servir una serie creíble.
ESTRUCTURA: Tuple[str, ...] = (
    "AREAS DE PROTECCION ESTRICTA",
    "RESERVAS CIENTIFICAS",
    "SANTUARIOS DE MAMIFERSO MARINOS",          # el emisor escribe «Mamiferso»
    "RESERVA BIOLOGICA",
    "PARQUES NACIONALES",
    "PARQUE NACIONALES",                        # sin la «s», es la subcategoría
    "PARQUES NACIONALES SUBMARINOS",
    "MONUMENTOS NATURALES",                     # grupo
    "MONUMENTOS NATURALES",                     # y subcategoría: el mismo rótulo
    "REFUGIOS DE VIDA SILVESTRE",
    "AREAS DE MANEJO DE HABITAT/ ESPECIES",
    "REFUGIOS DE VIDA SILVESTRE",               # otra vez, bajo otro grupo
    "SANTUARIO MARINO",
    "RESERVSA NATURALES",                       # el emisor escribe «Reservsa»
    "RESERVAS FORESTALES",
    "PAISAJES PROTEGIDOS",
    "VIA PANORAMICA",
    "AREAS NATURALES DE RECREO",
    "CORREDOR ECOLOGICO",
)

#: Índices de los seis grupos dentro de `ESTRUCTURA`. Lo que hay debajo de cada uno, hasta el
#: siguiente, son sus subcategorías.
GRUPOS: Tuple[int, ...] = (0, 4, 7, 10, 13, 15)

#: Cuánto puede fallar la suma de las subcategorías contra su grupo, en km², antes de
#: DECLARARLO. No se descarta el año: se nombra el desajuste, que es del emisor.
TOLERANCIA_KM2 = 2.0

#: Banda de plausibilidad de la razón. La superficie protegida de un país no baja del 1% ni
#: pasa del 60%; fuera de eso lo que falló es el denominador o la suma.
BANDA_PCT = (1.0, 60.0)

_TIMEOUT = 180.0


class AreasProtegidasError(RuntimeError):
    """No se pudo leer el cuadro. NUNCA se degrada a «no hay dato»."""


@dataclass(frozen=True)
class Superficie:
    """Un año, con lo que hace falta para saber qué se puede afirmar de él."""

    anio: int
    terrestre_km2: float
    marina_km2: float
    #: Qué grupos no cuadran con sus subcategorías ESE año, según el propio emisor.
    desajustes: Tuple[str, ...] = ()


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t if t is not None else ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _num(x: object) -> float:
    try:
        return float(str(x).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def leer_filas(texto: str) -> List[List[str]]:
    """Las filas de datos del CSV, sin la cabecera."""
    filas = list(csv.reader(io.StringIO(texto), delimiter=SEPARADOR))
    if not filas:
        raise AreasProtegidasError("el archivo vino vacío")
    return [f for f in filas[1:] if f and len(f) >= 5 and f[4].strip().isdigit()]


def superficies_de(filas: Sequence[Sequence[str]]) -> List[Superficie]:
    """La superficie protegida por año, sumando SOLO los seis grupos de categoría."""
    anios = sorted({int(f[4]) for f in filas})
    if not anios:
        raise AreasProtegidasError("ninguna fila declara año")
    out: List[Superficie] = []
    for anio in anios:
        d = [f for f in filas if int(f[4]) == anio]
        rot = tuple(_norm(f[0]) for f in d)
        if rot != ESTRUCTURA:
            faltan = [r for r in ESTRUCTURA if r not in rot]
            raise AreasProtegidasError(
                f"{anio}: el cuadro trae {len(d)} filas y no coinciden con la estructura "
                f"declarada. Leer por posición ahora sumaría la categoría de al lado. "
                f"Sin coincidencia: {faltan[:3]}")
        desajustes: List[str] = []
        for k, g in enumerate(GRUPOS):
            fin = GRUPOS[k + 1] if k + 1 < len(GRUPOS) else len(d)
            sub_t = sum(_num(d[i][2]) for i in range(g + 1, fin))
            sub_m = sum(_num(d[i][3]) for i in range(g + 1, fin))
            if abs(sub_t - _num(d[g][2])) > TOLERANCIA_KM2:
                desajustes.append(f"{d[g][0].strip()} (terrestre)")
            if abs(sub_m - _num(d[g][3])) > TOLERANCIA_KM2:
                desajustes.append(f"{d[g][0].strip()} (marina)")
        out.append(Superficie(
            anio=anio,
            terrestre_km2=round(sum(_num(d[i][2]) for i in GRUPOS), 3),
            marina_km2=round(sum(_num(d[i][3]) for i in GRUPOS), 3),
            desajustes=tuple(desajustes)))
    return out


def razon_terrestre(superficie: Superficie, area_terrestre_km2: float) -> float:
    """`% del área terrestre del país` que está bajo protección.

    Es TERRESTRE sobre terrestre, y lo decide el oráculo y no una opinión: así 2009 da
    24,19% contra los 24,4 que fija la ley. Cualquier variante que meta lo marino se va a
    un dígito.
    """
    if not area_terrestre_km2:
        raise AreasProtegidasError(
            "sin el área terrestre del país no hay razón que computar; servir los km² "
            "sueltos sería servir otra magnitud")
    pct = superficie.terrestre_km2 / area_terrestre_km2 * 100.0
    if not (BANDA_PCT[0] <= pct <= BANDA_PCT[1]):
        raise AreasProtegidasError(
            f"{superficie.anio}: {pct:.2f}% queda fuera de la banda {BANDA_PCT}. Lo que "
            f"falló es el denominador o la suma de grupos, no el país.")
    return round(pct, 3)


def fetch() -> List[Superficie]:  # pragma: no cover - red
    """Descarga el conjunto del portal nacional y devuelve la superficie por año."""
    import httpx

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": "sdq-mip/1.0"}) as c:
        r = c.get(URL)
        r.raise_for_status()
        texto = r.content.decode(ENCODING)
    serie = superficies_de(leer_filas(texto))
    con_desajuste = [s.anio for s in serie if s.desajustes]
    if con_desajuste:
        logger.info("[areas_protegidas] %d años en que el emisor no cuadra con sus "
                    "subcategorías: %s", len(con_desajuste), con_desajuste)
    return serie


def fetch_area_terrestre() -> Optional[float]:  # pragma: no cover - red
    """El área terrestre del país: UN solo valor para toda la serie.

    Se toma la añada más reciente y se aplica a los catorce años a propósito. El emisor
    revisa el área nacional de tanto en tanto —el catálogo trae 48.198 y 48.310 km²— y usar
    la de cada año haría que una revisión del DENOMINADOR se leyera como un cambio en la
    superficie protegida. Es la misma lección que dejó el PIB en el indicador 2.33.
    """
    from shared.data.wdi_client import fetch_wb_indicator

    filas, _ = fetch_wb_indicator(CODIGO_AREA_TERRESTRE, ["DOM"], mrv=25)
    valores: Dict[int, float] = {int(r["date"]): float(r["value"]) for r in filas
                                 if isinstance(r, dict) and r.get("value") is not None}
    return max(valores.items())[1] if valores else None
