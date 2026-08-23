"""Latinobarómetro — confianza en los partidos políticos (indicador 1.1 de la END 2030).

El emisor no publica descarga abierta de resultados: sirve las tabulaciones desde una
herramienta de consulta interactiva. Detrás de esa herramienta hay un servicio web que
devuelve frecuencias, porcentajes y base sin no-respuesta, y es el que consume este módulo.

**El contrato NO está documentado**, y eso decide cómo está escrito todo lo de abajo. Se
dedujo leyendo el código de la propia página, así que el conector nace con fecha de
vencimiento desconocida: el emisor puede cambiarlo sin avisar y sin romperlo visiblemente.
Por eso cada supuesto se comprueba y cada comprobación falla RUIDOSA. Un conector frágil que
se calla es peor que no tenerlo — devuelve media serie y nadie se entera.

Cómo funciona:

  1. ``POST /ws/oda/stats/session/2`` con ``{"sid": null, "page": null}`` abre sesión y
     devuelve un ``sid``. Todas las llamadas siguientes lo mandan en la cabecera
     ``odaSession``; sin ella el servicio responde un error genérico.
  2. ``POST /ws/oda/question/2/{pregunta}`` con el país en ``amids`` y la ronda en
     ``roundEquiv`` devuelve la tabulación de ESA ronda. La pregunta se identifica una sola
     vez: ``roundEquiv`` la sigue entre rondas, que es como la herramienta permite ver la
     serie sin volver al índice.

**El guard que más importa: cuando el país no fue encuestado, el servicio NO falla.** Cae
al agregado regional y devuelve una tabla con base de veinte mil casos, que es la de los
dieciocho países juntos. Publicar eso como cifra dominicana sería exactamente el error que
esta plataforma existe para no cometer. Se detecta por el rótulo con el que el propio emisor
declara el ámbito —``samplestext``—: si no nombra al país pedido, se descarta el año.

El rótulo llega a veces en inglés y a veces en español —el mismo servicio devolvió
«República Dominicana» para 2010 y «Dominican Republic» para 2024— así que los nombres
aceptados se declaran, no se traducen al vuelo.
"""
from __future__ import annotations

import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.latinobarometro")

BASE = "https://www.latinobarometro.org/ws/oda"
COLECCION = 2

#: Los términos: el emisor NO los declara en sus páginas públicas —ni permite ni prohíbe—.
#: La decisión de publicar con atribución explícita es del dueño, tomada el 2026-08-22, y
#: está registrada con su razonamiento en la lista blanca del expediente END 2030
#: (`fuentes_admitidas`, entrada `encuesta_regional`). La atribución no es opcional: la
#: computa `modules.law_intel.ai_context.atribuciones_obligatorias`.
LICENSE = "cita con atribución · decidido 2026-08-22"
SOURCE = "Latinobarómetro"

#: Ámbito del país, en el código numérico ISO 3166 que usa el emisor.
AMBITO_RD = 214
#: Cómo nombra el emisor a ese ámbito. Las dos formas son suyas, observadas en respuestas
#: reales del mismo servicio para años distintos.
NOMBRES_RD = ("dominican republic", "republica dominicana")

#: Pregunta «Confianza en los partidos políticos» (variable P14ST.G del emisor) tal como la
#: identifica el índice de la ronda 2010, que es la que fija la línea base de la ley.
PREGUNTA_PARTIDOS = 198114
RONDA_INDICE = 339

#: Ronda del emisor → año. Se declara y no se infiere: los identificadores no son
#: correlativos ni guardan relación con el año (2013 es 573 y 2015 es 1539).
RONDAS: Dict[int, int] = {
    324: 1995, 326: 1996, 327: 1997, 328: 1998, 329: 2000, 330: 2001, 331: 2002,
    332: 2003, 333: 2004, 334: 2005, 335: 2006, 336: 2007, 337: 2008, 338: 2009,
    339: 2010, 340: 2011, 573: 2013, 1539: 2015, 1560: 2016, 1566: 2017, 1585: 2018,
    1634: 2020, 1661: 2023, 1696: 2024,
}

#: Categorías de la escala de confianza. La magnitud que fija la ley es la suma de las dos
#: primeras sobre la base SIN no-respuesta: para 2010 eso da 22,3% contra los 22,2% de la
#: línea base legal. Ninguna otra combinación se acerca, y por eso el conjunto va acá y no
#: como un parámetro: cambiarlo cambia el indicador.
CATEGORIAS_CONFIA = (1, 2)
#: Las cuatro sustantivas. Si el emisor agregara o quitara una, la magnitud dejaría de ser
#: la misma y hay que enterarse.
CATEGORIAS_SUSTANTIVAS = (1, 2, 3, 4)

#: Una base de este tamaño no es la de un país: es la de los dieciocho juntos. Es el segundo
#: cinturón, por si el emisor algún día rotula el ámbito y aun así agrega.
BASE_MAXIMA_DE_UN_PAIS = 5000

_TIMEOUT = 90.0


class LatinobarometroUnavailable(RuntimeError):
    """El emisor no respondió, o respondió algo que no se puede usar sin inventar."""


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower())
                if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def abrir_sesion(cliente: Optional[Any] = None) -> str:  # pragma: no cover - red
    """El `sid` que hay que mandar en cada consulta. Sin él, el servicio devuelve un error
    genérico sin decir que falta la sesión."""
    import httpx

    c = cliente or httpx
    try:
        r = c.post(f"{BASE}/stats/session/{COLECCION}", json={"sid": None, "page": None},
                   timeout=_TIMEOUT)
        r.raise_for_status()
        sid = r.json().get("sid")
    except Exception as e:  # noqa: BLE001 — cualquier fallo acá deja el resto sin sentido
        raise LatinobarometroUnavailable(
            f"no se pudo abrir sesión con el emisor ({type(e).__name__}: {e})") from e
    if not sid:
        raise LatinobarometroUnavailable("el emisor abrió sesión sin devolver identificador")
    return str(sid)


def _cuerpo(ronda: int, ambito: int) -> Dict[str, object]:
    return {
        "cuid": RONDA_INDICE, "amids": str(ambito), "saids": "", "idioma": 1,
        "roundEquiv": ronda, "cross1": 0, "cross2": 0, "showEmpty": True,
        "timeseries": False, "maps": False, "mapa": "latinobarometro", "trad": -1,
    }


def parse_confianza(payload: Dict[str, object],
                    nombres_del_ambito: Sequence[str] = NOMBRES_RD) -> Optional[float]:
    """`% que declara mucha o algo de confianza`, sobre la base sin no-respuesta.

    Devuelve ``None`` cuando la respuesta NO es del ámbito pedido — que es el caso de los
    años en que el país no entró en la encuesta y el servicio cae al agregado regional en
    silencio. Levanta cuando la respuesta llega con una forma que no se puede interpretar:
    ahí callarse sería inventar.
    """
    if not payload.get("success"):
        return None
    rotulo = _norm(payload.get("samplestext") or payload.get("footerTable"))
    if not rotulo:
        return None                       # el emisor no declara ámbito: no es de nadie
    if rotulo not in {_norm(n) for n in nombres_del_ambito}:
        return None                       # es de otro ámbito, o de varios

    resultado: Dict[str, Any] = payload.get("resultado") or {}   # type: ignore[assignment]
    tablas = resultado.get("tables") or []
    if not tablas:
        raise LatinobarometroUnavailable("la respuesta no trae tabla de resultados")
    tabla = tablas[0]
    filas = tabla.get("rows") or []
    bases = tabla.get("baseSinMissing") or []
    if not bases or not bases[0]:
        raise LatinobarometroUnavailable("la respuesta no trae base sin no-respuesta")
    base = float(bases[0])
    if base > BASE_MAXIMA_DE_UN_PAIS:
        raise LatinobarometroUnavailable(
            f"base de {base:.0f} casos para un solo país: el servicio agregó ámbitos y el "
            f"rótulo no lo dijo")

    por_cat = {}
    for f in filas:
        try:
            por_cat[int(f["valorCat"])] = float(f["frecuenciasN"][0])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LatinobarometroUnavailable(f"fila ilegible en la tabla: {f!r}") from e
    faltan = [c for c in CATEGORIAS_SUSTANTIVAS if c not in por_cat]
    if faltan:
        raise LatinobarometroUnavailable(
            f"la escala del emisor cambió: faltan las categorías {faltan}. La magnitud que "
            f"fija la ley es la suma de las dos primeras y sin ellas no es la misma.")
    confia = sum(por_cat[c] for c in CATEGORIAS_CONFIA)
    return round(confia / base * 100.0, 2)


def fetch_confianza_partidos(ambito: int = AMBITO_RD,
                             nombres: Sequence[str] = NOMBRES_RD
                             ) -> List[Tuple[int, float]]:  # pragma: no cover - red
    """`[(año, % con mucha o algo de confianza)]` para el ámbito pedido.

    Los años en que el emisor no encuestó al país se OMITEN, no se rellenan. Y si no
    sobrevive ninguno, se levanta: una serie vacía devuelta en silencio se lee como que el
    emisor dejó de publicar, cuando lo que pasó es que cambió el contrato.
    """
    import httpx

    sid = abrir_sesion()
    cabeceras = {"Content-Type": "application/json", "odaSession": sid,
                 "User-Agent": "Mozilla/5.0 (compatible; sdq-mip/1.0)"}
    url = f"{BASE}/question/{COLECCION}/{PREGUNTA_PARTIDOS}"
    out: List[Tuple[int, float]] = []
    omitidos: List[int] = []
    with httpx.Client(timeout=_TIMEOUT, headers=cabeceras) as cliente:
        for ronda, anio in sorted(RONDAS.items(), key=lambda t: t[1]):
            try:
                r = cliente.post(url, content=json.dumps(_cuerpo(ronda, ambito)))
                r.raise_for_status()
                pct = parse_confianza(r.json(), nombres)
            except LatinobarometroUnavailable:
                raise
            except Exception as e:  # noqa: BLE001
                raise LatinobarometroUnavailable(
                    f"la consulta del año {anio} falló ({type(e).__name__}: {e})") from e
            if pct is None:
                omitidos.append(anio)
                continue
            out.append((anio, pct))
    if not out:
        raise LatinobarometroUnavailable(
            "ningún año devolvió datos del ámbito pedido: o el emisor cambió el contrato, o "
            "cambió cómo rotula los ámbitos")
    logger.info("[latinobarometro] %d años con dato; %d omitidos por no ser del ámbito: %s",
                len(out), len(omitidos), omitidos)
    return out
