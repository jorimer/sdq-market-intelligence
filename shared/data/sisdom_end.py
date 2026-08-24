"""SISDOM — «Indicadores Área Especial END», la hoja que el Estado publica para su propia ley.

El Sistema de Indicadores Sociales de la República Dominicana publica un libro con una hoja
por indicador de la END, con la serie anual, el total del país y las desagregaciones. Es el
metaregistro del que sale, para medio centenar de indicadores del Eje 2, **quién es el emisor
y con qué instrumento se mide** — que era justamente la clase de bloqueo que el expediente
trataba caso por caso.

**El instrumento cambió en 2016 y el libro lo declara con un asterisco.** La Encuesta
Nacional de Fuerza de Trabajo (ENFT) se sustituyó por la Encuesta Nacional Continua (ENCFT),
y la hoja marca con `*` las columnas de la nueva. Ese asterisco no es cosmético: **2016
aparece DOS veces**, una por cada encuesta, y en el 2.40 dan 0,91630 y 0,90724. Es un
solapamiento, no un empalme — las dos series no se encadenan sin declarar la convención.

Por eso el instrumento VIAJA con cada observación. Una serie que cruza 2016 sin decir con qué
encuesta se midió cada tramo se compara contra una línea base de 2010 que es de la otra, y el
salto se lee como cambio del fenómeno.

**El emisor cambió de nombre entre ediciones y el pie lo dice.** La edición 2024 firma
«Elaborado por el VAES, Ministerio de Economía, Planificación y Desarrollo»; la 2025,
«Elaborado por el VE, Ministerio de Hacienda y Economía». Es la Ley 45-25 vista desde el
dato: la función siguió y cambió de casa. Las dos ediciones coinciden AL DÍGITO en los años
que comparten, así que no hay problema de añada — hay que usar las dos porque cubren tramos
distintos: la vieja llega a las líneas base de 2010, la nueva llega al año corriente.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.sisdom_end")

SOURCE = "SISDOM"
LICENSE = "SISDOM (VAES/MEPyD) — indicadores sociales oficiales, uso público con cita"

#: Las dos ediciones que hacen falta, y por qué las dos. La del MEPyD llega hasta las líneas
#: base de la ley (2000-2024); la de Hacienda arranca en 2016 y trae el año corriente. Quedarse
#: con una sola pierde un extremo: la migración institucional truncó la serie publicada.
EDICIONES = {
    2024: ("https://mepyd.gob.do/wp-admin/admin-ajax.php?juwpfisadmin=false&action=wpfd"
           "&task=file.download&wpfd_category_id=22154&wpfd_file_id=421934"),
    2025: ("https://www.hacienda.gob.do/wp-content/uploads/2026/07/"
           "SISDOM-2025.-Indicadores-Area-Especial-END.xlsx"),
}

#: Cómo empieza el rótulo de la fila del total nacional. Se compara por PREFIJO porque el
#: libro usa al menos cinco variantes vivas —«Total país», «Total Nacional», «Nacional»,
#: «Nacional1» y «Nacional 1 c»—, donde el sufijo es la llamada a una nota al pie. Exigir
#: igualdad exacta dejaba fuera ocho hojas sin que nada avisara: la lectura devolvía vacío, y
#: vacío se lee como «el emisor no publica».
PREFIJOS_NACIONALES = ("TOTAL PAIS", "TOTAL NACIONAL", "NACIONAL")
ROTULOS_NACIONALES = PREFIJOS_NACIONALES          # nombre anterior, se conserva

#: Cómo empieza el rótulo de la fila de encabezado. También por prefijo: el libro alterna
#: «Desagregaciones», «Desagregación» y «Desagregaciones1».
PREFIJO_DESAGREGACION = "DESAGREGACI"
ROTULO_DESAGREGACION = "DESAGREGACIONES"

#: Qué encuesta produce cada columna. Lo declara la Nota 5 del propio libro: el asterisco es
#: la ENCFT. Antes de 2016 no hay asterisco y es la ENFT.
INSTRUMENTO_CON_ASTERISCO = "ENCFT"
INSTRUMENTO_SIN_ASTERISCO = "ENFT"

#: El año en que conviven las dos encuestas. Es el único con dos observaciones, y es el que
#: permitiría declarar un factor de empalme — si algún día se decide declararlo.
ANIO_DE_SOLAPAMIENTO = 2016

_TIMEOUT = 300.0


class SisdomError(RuntimeError):
    """No se pudo leer la hoja. NUNCA se degrada a «no hay dato»."""


@dataclass(frozen=True)
class Observacion:
    """Un año de un indicador, con el instrumento que lo midió."""

    anio: int
    valor: float
    #: `ENFT` o `ENCFT`. Sin esto, una serie que cruza 2016 se compara contra una línea base
    #: medida por la otra encuesta y el salto se lee como cambio del fenómeno.
    instrumento: str
    #: La edición del libro de la que salió, para poder rastrear una discrepancia.
    edicion: Optional[int] = None


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t if t is not None else ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def anio_de(celda: object) -> Optional[int]:
    """El año de una celda de encabezado, o `None`.

    El emisor mezcla tipos en la misma fila: `2000` como texto, `2001.0` como número y
    `2016*` como texto con la marca de la encuesta nueva.
    """
    t = str(celda).strip().replace("*", "")
    if t.endswith(".0"):
        t = t[:-2]
    return int(t) if re.fullmatch(r"(?:19|20)\d\d", t) else None


def instrumento_de(celda: object) -> str:
    """Qué encuesta midió esa columna, según la marca que el propio libro declara."""
    return (INSTRUMENTO_CON_ASTERISCO if "*" in str(celda)
            else INSTRUMENTO_SIN_ASTERISCO)


def nombre_de_hoja(hojas: Sequence[str], indicador: str) -> Optional[str]:
    """La hoja de un indicador, tolerando cómo el emisor la nombra.

    La del 2.40 se llama `« END 2.40»`, con un espacio ADELANTE. Buscar por igualdad exacta
    la pierde, y perderla se lee como que el indicador no tiene fuente — que es precisamente
    el estado en el que estuvo hasta hoy.
    """
    objetivo = _norm(f"END {indicador}")
    for h in hojas:
        if _norm(h) == objetivo:
            return h
    return None


def es_fila_nacional(rotulo: object) -> bool:
    r = _norm(rotulo)
    return any(r.startswith(p) for p in PREFIJOS_NACIONALES)


def fila_del_total(primera_columna: Sequence[Any]) -> Optional[int]:
    for i, celda in enumerate(primera_columna):
        if es_fila_nacional(celda):
            return i
    return None


def fila_de_encabezado(filas: Sequence[Sequence[Any]]) -> Optional[int]:
    """La fila de años: la que rotula la columna de desagregaciones.

    Se ancla en el rótulo y no en «la fila con más años» porque acá el ancla existe y es
    estable; donde no existe —la hoja COFOG de Hacienda— hay que contar años, y ese camino
    es más frágil.
    """
    for i, f in enumerate(filas):
        if f and _norm(f[0]).startswith(PREFIJO_DESAGREGACION):
            return i
    return None


def leer_hoja(filas: Sequence[Sequence[Any]],
              edicion: Optional[int] = None,
              variante: Optional[str] = None) -> List[Observacion]:
    """La serie nacional de una hoja ya leída como lista de filas.

    **Recorre la hoja en BLOQUES**, no busca un encabezado y una fila. Una hoja puede traer
    varios encabezados apilados —el 2.25 parte los años en dos, 1981-2000 y 2001-2024, cada
    uno con su propia fila nacional— y quedarse con el primero pierde media serie sin avisar.

    **Y una hoja puede traer varias filas nacionales**, que son metodologías distintas del
    mismo indicador: el 2.23 tiene cuatro —SINAVE corregido por subregistro, mortalidad
    notificada, la serie nueva que integra certificado de defunción con vigilancia e INACIF,
    y las estimaciones de ENDESA—. Ahí `variante` dice cuál, comparando por prefijo contra el
    rótulo. Sin `variante` se toman todas y el llamador decide; devolver «la primera» sería
    elegir una metodología por su posición en la hoja.

    Devuelve **todas** las observaciones, incluidas las DOS de 2016. No se elige una: son dos
    mediciones distintas del mismo año, y cuál corresponde depende de contra qué se compare.
    """
    out: List[Observacion] = []
    encabezado: Optional[Sequence[Any]] = None
    vistos: set = set()
    for f in filas:
        rot = _norm(f[0] if f else "")
        if rot.startswith(PREFIJO_DESAGREGACION):
            encabezado = f
            continue
        if encabezado is None or not es_fila_nacional(rot):
            continue
        if variante is not None and not rot.startswith(_norm(variante)):
            continue
        vistos.add(str(f[0]).strip())
        for c, celda in enumerate(encabezado):
            a = anio_de(celda)
            if a is None or c >= len(f):
                continue
            v = f[c]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
                continue
            out.append(Observacion(anio=a, valor=float(v),
                                   instrumento=instrumento_de(celda), edicion=edicion))
    if encabezado is None:
        raise SisdomError(
            f"la hoja no trae ninguna fila que empiece por «{PREFIJO_DESAGREGACION}»: o "
            f"cambió el formato del libro, o no es una hoja de indicador.")
    if not out:
        raise SisdomError(
            "ninguna fila nacional dio dato"
            + (f" para la variante «{variante}»" if variante else "")
            + f". Filas nacionales de la hoja: {sorted(vistos) or 'ninguna'}. Servir una "
              f"desagregación como si fuera el país publica otra magnitud.")
    return out


def serie_de(observaciones: Sequence[Observacion], instrumento: str) -> Dict[int, float]:
    """`{anio: valor}` de UN instrumento. Es la única forma comparable de la serie.

    Mezclar ENFT y ENCFT en un mismo diccionario es lo que hace que el cambio de encuesta se
    lea como un cambio del fenómeno: en 2016, que es el año que las dos midieron, el 2.40 da
    0,91630 con la vieja y 0,90724 con la nueva.
    """
    return {o.anio: o.valor for o in observaciones if o.instrumento == instrumento}


def salto_en_el_solapamiento(observaciones: Sequence[Observacion]) -> Optional[Tuple[float, float]]:
    """`(valor ENFT, valor ENCFT)` del año que las dos encuestas midieron, si están las dos.

    No se usa para empalmar —el emisor no publica factor de empalme y fabricarlo sería
    inventar una convención— sino para PODER DECLARAR de qué tamaño es el escalón.
    """
    viejo = next((o.valor for o in observaciones
                  if o.anio == ANIO_DE_SOLAPAMIENTO
                  and o.instrumento == INSTRUMENTO_SIN_ASTERISCO), None)
    nuevo = next((o.valor for o in observaciones
                  if o.anio == ANIO_DE_SOLAPAMIENTO
                  and o.instrumento == INSTRUMENTO_CON_ASTERISCO), None)
    return (viejo, nuevo) if viejo is not None and nuevo is not None else None


def fetch(indicador: str) -> List[Observacion]:  # pragma: no cover - red + hoja de cálculo
    """La serie de un indicador, uniendo las dos ediciones publicadas.

    Las ediciones coinciden al dígito en los años que comparten —comprobado el 2026-08-24 en
    el 2.40— así que ante empate gana la más nueva y la discrepancia, si aparece, se registra
    en el log en vez de resolverse en silencio.
    """
    import io

    import httpx
    import pandas as pd

    por_clave: Dict[Tuple[int, str], Observacion] = {}
    fallos: List[str] = []
    for edicion, url in sorted(EDICIONES.items()):
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": "sdq-mip/1.0"}) as c:
                r = c.get(url)
                r.raise_for_status()
                libro = io.BytesIO(r.content)
            hoja = nombre_de_hoja(pd.ExcelFile(libro).sheet_names, indicador)
            if hoja is None:
                fallos.append(f"{edicion}: sin hoja para el indicador {indicador}")
                continue
            df = pd.read_excel(libro, sheet_name=hoja, header=None)
            fuente = INDICADORES.get(indicador)
            obs = leer_hoja([list(df.iloc[k]) for k in range(len(df))], edicion=edicion,
                            variante=fuente.variante if fuente else None)
        except Exception as e:  # noqa: BLE001 — una edición caída no se lleva a la otra
            fallos.append(f"{edicion}: {e}")
            continue
        for o in obs:
            clave = (o.anio, o.instrumento)
            anterior = por_clave.get(clave)
            if anterior is not None and abs(anterior.valor - o.valor) > 1e-9:
                logger.warning("[sisdom] %s %s (%s): la edición %d da %.6f y la %d %.6f",
                               indicador, o.anio, o.instrumento, anterior.edicion,
                               anterior.valor, edicion, o.valor)
            por_clave[clave] = o
    if not por_clave:
        raise SisdomError(
            f"ninguna edición del libro dio una serie para el indicador {indicador}. "
            + " · ".join(fallos))
    if fallos:
        logger.warning("[sisdom] %s: %s", indicador, " · ".join(fallos))
    return sorted(por_clave.values(), key=lambda o: (o.anio, o.instrumento))

#: Qué indicadores de la END se sirven desde este libro, con la hoja EXACTA y por qué esa.
#: Campos con nombre y no una tupla: son cinco datos por entrada y el quinto —la variante
#: metodológica— solo aplica a uno, así que posicionalmente se pasa mal.
@dataclass(frozen=True)
class Fuente:
    hoja: str
    tema: str
    unidad: str
    por_que: str
    #: Cuál fila nacional, cuando la hoja trae varias metodologías del mismo indicador.
    variante: Optional[str] = None


INDICADORES: Dict[str, Fuente] = {
    "2.8": Fuente("END 2.8a", "preschool_net_coverage", "%",
                  "Tasa neta de cobertura de nivel inicial, de ENCUESTAS DE HOGARES. Las "
                  "otras dos hojas miden la neta AJUSTADA (2.8b) y la misma tasa con "
                  "registros y proyecciones (2.8c); la ley fija su base sobre la de hogares."),
    "2.24": Fuente("END 2.24", "malaria_mortality_rate", "por 100.000 hab.",
                   "Mortalidad asociada a malaria. La línea base legal (0,14 en 2010) es la "
                   "cifra de esta hoja al dígito."),
    "2.28": Fuente("END 2.28", "child_underweight_rate", "%",
                   "Desnutrición GLOBAL (peso/edad) en menores de 5. Δ 0,0% contra la base "
                   "legal. OJO: la serie tiene DOS puntos, 2007 y 2013 — el emisor dejó de "
                   "medirla y ninguna meta de la ley es evaluable."),
    "2.29": Fuente("END 2.29", "child_wasting_rate", "%",
                   "Desnutrición AGUDA (peso/talla). Mismo caso que el 2.28: Δ 0,0% y la "
                   "serie termina en 2013."),
    "2.30": Fuente("END 2.30", "child_stunting_rate", "%",
                   "Desnutrición CRÓNICA (talla/edad). Mismo caso: Δ 0,0% y termina en 2013."),
    "2.31": Fuente("END 2.31", "vertical_hiv_transmission", "%",
                   "Hijos de madres VIH positivas que resultan seropositivos. Δ 0,0%."),
    "2.32": Fuente("END 2.32", "advanced_hiv_on_art", "%",
                   "Portadores de VIH con infección avanzada que reciben antirretrovirales. "
                   "Δ 0,0%."),
    "2.34": Fuente("END 2.34", "improved_sanitation_access", "%",
                   "Acceso a servicios sanitarios mejorados. Término idéntico al de la ley."),
    "2.35": Fuente("END 2.35", "public_network_water_access", "%",
                   "Acceso a agua de la RED PÚBLICA dentro o fuera de la vivienda. Término "
                   "idéntico al de la ley, que es lo que separa esta serie de la de agua «al "
                   "menos básica» — esa incluye pozos protegidos y la ley pide red pública."),
    "2.37": Fuente("END 2.37a", "broad_unemployment_rate", "%",
                   "Tasa de desocupación AMPLIADA. La ley dice «tasa de desocupación» a secas "
                   "y el emisor publica las dos; el oráculo desempata: la ampliada reproduce "
                   "la línea base con Δ 1,8% y la abierta se va 63,5%."),
    "2.40": Fuente(" END 2.40", "income_gender_ratio", "razón F/M (1,0 = paridad)",
                   "Ingreso laboral POR HORA de mujeres en jornada completa sobre el de los "
                   "hombres. La hoja se llama con un espacio ADELANTE y buscarla por igualdad "
                   "exacta la pierde. Ojo con su Nota 2, que dice «ingreso base mensual de "
                   "toda la población ocupada»: contradice a la ficha oficial del propio "
                   "emisor y describe otra magnitud. El oráculo la desempata — la ficha "
                   "reproduce la línea base."),
    "2.47": Fuente("END 2.47", "child_labour_6_14", "%",
                   "Niños y niñas de 6 a 14 años que trabajan. Término y tramo etario "
                   "idénticos a los de la ley."),
    "2.48": Fuente("END 2.48", "neet_unemployed_15_19", "%",
                   "Jóvenes de 15 a 19 años que no estudian y están desempleados. Término "
                   "idéntico al de la ley."),
    "3.10": Fuente("END 3.10", "tertiary_net_enrollment", "%",
                   "Tasa neta de matrícula de nivel superior, 18 a 24 años. Término idéntico."),
}
