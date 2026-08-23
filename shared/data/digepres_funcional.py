"""Gasto del Gobierno Central por clasificación funcional (DIGEPRES) — indicador 2.33.

El emisor publica un informe anual de ejecución presupuestaria y dentro de él un cuadro de
clasificación funcional con una línea de **Salud**. Es la magnitud que la ley fija: se
comprobó el 2026-08-23 contra el informe de 2009, cuyo presupuesto vigente da 1,389% del PIB
frente a los 1,4 que fija la línea base legal — Δ 0,8%.

**El cuadro cambia de forma entre épocas, y ahí está todo el riesgo.** Dos formas conviven:

* la CLÁSICA (informes de 2008 a 2011): ``Salud | vigente | ejecutado | % ejecución``;
* la NUMERADA (2015 en adelante): ``4.2 - Salud`` seguida de una decena de columnas, entre
  ellas el **% del PIB que el propio emisor computa**.

Y el mismo cuadro cambia de UNIDAD: el informe de 2009 va en millones de RD$ y el de 2016 en
unidades de peso, mil veces más grande. Ese es el modo de falla que este módulo persigue —no
que se rompa, sino que devuelva una serie plausible mil veces corrida—, y por eso la razón
contra el PIB se comprueba SIEMPRE contra una banda de plausibilidad antes de servirse.

**Se leen las columnas por su encabezado, no por su posición.** Un cuadro que agrega una
columna corre todas las demás, y leer por índice serviría la variación donde se espera el
devengado sin que nada avise. Cuando el emisor publica su propio % del PIB, se usa como
segundo cinturón: si nuestra razón y la suya discrepan, algo se leyó mal.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.digepres")

LICENSE = "DIGEPRES — informe oficial de ejecucion presupuestaria (Ley 423-06)"
SOURCE = "DIGEPRES"

#: Biblioteca de medios del emisor. Su página de informes NO entrega el archivo: los botones
#: de los años viejos apuntan a documentos equivocados —el de 2009 sirve la Ley de Presupuesto
#: de 2012— y los recientes son acordeones que arma el navegador. Comprobado el 2026-08-23.
MEDIA_API = "https://digepres.gob.do/wp-json/wp/v2/media"

#: Rótulo del cuadro. Se busca normalizado —sin tildes y en mayúsculas— porque el emisor
#: alterna «Clasificación Funcional» y «CLASIFICACION FUNCIONAL DE LOS GASTOS».
ROTULO_CUADRO = "CLASIFICACION FUNCIONAL"

#: Todo lo que en un rotulo NO es la palabra: el codigo de funcion, los puntos y cualquier
#: variedad de guion. El extractor del emisor devuelve guion BLANDO (U+00AD) seguido de otro
#: guion en los informes de 2015 y 2016, y una fila que no los limpie sencillamente no
#: aparece — que fue lo que pasó en la primera corrida.
_RUIDO_DE_ROTULO = re.compile("[\\d.\\s\\u00ad\\u2010-\\u2015-]+")

#: Banda de plausibilidad de la razón contra el PIB. El gasto público en salud de un país
#: cabe holgadamente acá; fuera de la banda lo que falló es la UNIDAD o la columna, no el
#: país. Es el guard que impide servir una serie mil veces corrida.
BANDA_PCT_PIB = (0.3, 12.0)

#: Cuánto pueden diferir nuestra razón y la que publica el emisor. Amplio a propósito: el
#: emisor redondea a un decimal, así que sobre 1,9% un punto de redondeo ya son ~5%.
TOLERANCIA_CONTRA_EL_EMISOR_PCT = 15.0

_TIMEOUT = 300.0


class DigepresError(RuntimeError):
    """No se pudo leer el cuadro. NUNCA se degrada a «no hay dato»."""


@dataclass(frozen=True)
class GastoFuncional:
    """La línea de Salud de un año, con de dónde salió cada cifra."""

    anio: int
    pct_pib: float
    #: `emisor` cuando el propio cuadro publica la razón; `computado` cuando la calculamos
    #: contra el PIB nominal. Viaja porque no valen lo mismo.
    procedencia_de_la_razon: str
    monto: Optional[float] = None
    unidad_del_monto: Optional[str] = None
    pct_pib_del_emisor: Optional[float] = None


def _norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(t or ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _numero(t: str) -> Optional[float]:
    """Un número del cuadro, o `None`. Los paréntesis son negativos y los espacios sobran:
    el extractor parte «58,908.5» en «5» y «8,908.5» en más de un informe."""
    s = str(t).strip().replace(" ", "")
    neg = s.startswith("(") or s.endswith(")")
    s = s.strip("()%")
    if not re.fullmatch(r"-?[\d,.]+", s or ""):
        return None
    s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def lineas_de(palabras: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Agrupa palabras en filas por su coordenada vertical, ordenadas de izquierda a derecha.

    Se agrupa con tolerancia porque los superíndices y los guiones blandos del emisor caen
    unas décimas por encima de la línea, y separarlos partiría la fila en dos.
    """
    filas: Dict[int, List[Dict[str, Any]]] = {}
    for w in palabras:
        filas.setdefault(int(round(float(w["top"]) / 2.0)), []).append(w)
    return [sorted(ws, key=lambda w: float(w["x0"])) for _, ws in sorted(filas.items())]


def _pegar(ws: Sequence[Dict[str, Any]]) -> List[Tuple[float, str]]:
    """`[(x, texto)]` uniendo los fragmentos que el extractor partió dentro de un número.

    «5 8,908.5» son dos palabras y un solo número. Se pegan las que quedan pegadas en el papel
    —menos de tres puntos de separación— y solo cuando las dos son numéricas: unir texto con
    número inventaría una etiqueta.
    """
    out: List[Tuple[float, str]] = []
    for w in ws:
        t = str(w["text"])
        if out:
            x_ant, t_ant = out[-1]
            junto = float(w["x0"]) - x_ant < 3.0
            ambos_num = bool(re.search(r"\d", t_ant)) and bool(re.search(r"\d", t))
            if junto and ambos_num:
                out[-1] = (x_ant, t_ant + t)
                continue
        out.append((float(w["x0"]), t))
    return out


def rotulo_de(pegadas: Sequence[Tuple[float, str]]) -> str:
    """El rotulo de una fila del cuadro, aislado de todo lo demas.

    Tres cosas hay que sacarle, y cada una rompio una version anterior de esta funcion:

    * el CODIGO de funcion que abre la fila en la forma numerada («4.2»), que es un numero y
      por lo tanto no se puede cortar «en el primer numero»;
    * los GUIONES, incluido el blando (U+00AD) que el extractor devuelve pegado a otro guion
      en los informes de 2015 y 2016;
    * el PARENTESIS de apertura de un negativo —«( 1,110.8)»— que viaja como palabra suelta
      sin digitos y convertia el rotulo en «SALUD (».

    Se saltan los tokens de codigo y guion del principio, y despues se acumula hasta el
    primer token con digitos: ahi empieza la tabla.
    """
    solo_codigo = re.compile(r"^[\d.]+$")
    solo_guion = re.compile(r"^[\s\u00ad\u2010-\u2015-]+$")
    palabras: List[str] = []
    empezo = False
    for _, t in pegadas:
        if not empezo and (solo_codigo.match(t) or solo_guion.match(t)):
            continue
        if re.search(r"\d", t):
            break
        empezo = True
        palabras.append(t)
    return _RUIDO_DE_ROTULO.sub(" ", _norm(" ".join(palabras))).strip()


def fila_salud(filas: Sequence[Sequence[Dict[str, Any]]]) -> Optional[List[Tuple[float, str]]]:
    """La fila de Salud del cuadro, o `None`.

    Exige que el rotulo sea Salud Y NADA MAS. «Salud Publica y Asistencia Social» es una
    INSTITUCION y aparece en el cuadro institucional del mismo informe: mide otro universo y
    da una cifra bastante mayor, asi que confundirlas no rompe nada — publica otro numero.
    """
    for ws in filas:
        pegadas = _pegar(ws)
        if rotulo_de(pegadas) == "SALUD":
            return pegadas
    return None


#: Como rotula el emisor la columna del PIB. Varias formas conviven —«%PIB», «% PIB» y
#: «%PIB**» con llamada al pie— y se comparan sin el ruido para no depender de cual toco.
_RX_ENCABEZADO_PIB = re.compile(r"^%?\s*PIB\**$")


def x_de_columna(filas: Sequence[Sequence[Dict[str, Any]]], rotulo: str,
                 hasta: Optional[int] = None) -> Optional[float]:
    """Coordenada del encabezado pedido, buscando solo por ENCIMA de los datos.

    Las columnas se leen por su rotulo y no por su indice: un cuadro que agrega una columna
    corre todas las demas, y leer por posicion serviria la variacion donde se espera el
    devengado. Y se busca acotado, porque la palabra «PIB» aparece tambien en la prosa que
    rodea al cuadro — en el informe de 2018 hay tres parrafos que la usan antes de la tabla.
    """
    objetivo = _norm(rotulo)
    for k, ws in enumerate(filas):
        if hasta is not None and k >= hasta:
            break
        for w in ws:
            t = _norm(w["text"])
            if t == objetivo or (objetivo in ("PIB", "%PIB") and _RX_ENCABEZADO_PIB.match(t)):
                return float(w["x0"])
    return None


def leer_pct_pib_del_emisor(filas: Sequence[Sequence[Dict[str, Any]]]
                            ) -> Optional[float]:
    """El % del PIB que el propio emisor computa para Salud, si el cuadro lo trae.

    Se ubica por el encabezado «PIB» y se toma el porcentaje de la fila más cercano a esa
    columna. Cuando existe, es mejor cifra que la nuestra: no hay que dividir por un PIB que
    puede venir de otra fuente y de otra añada.
    """
    indice = next((k for k, ws in enumerate(filas)
                   if rotulo_de(_pegar(ws)) == "SALUD"), None)
    if indice is None:
        return None
    x_pib = x_de_columna(filas, "PIB", hasta=indice)
    fila = fila_salud(filas)
    if x_pib is None or not fila:
        return None
    candidatos = [(abs(x - x_pib), _numero(t)) for x, t in fila if t.strip().endswith("%")]
    candidatos = [(d, v) for d, v in candidatos if v is not None]
    if not candidatos:
        return None
    dist, v = min(candidatos, key=lambda c: c[0])
    # Un porcentaje a más de media página del encabezado no es el de esa columna.
    return v if dist < 60 else None


def razon_contra_pib(monto: float, unidad: str, pib_nominal: float) -> float:
    """`% del PIB` del monto, llevando la unidad declarada a pesos."""
    factor = {"millones": 1e6, "unidades": 1.0}.get(unidad)
    if factor is None:
        raise DigepresError(f"unidad '{unidad}' desconocida: el cuadro va en millones o en "
                            f"unidades de peso, y confundirlas corre la serie mil veces")
    if not pib_nominal:
        raise DigepresError("sin PIB nominal no hay razón que computar")
    return monto * factor / pib_nominal * 100.0


def verificar(pct: float, pct_emisor: Optional[float]) -> None:
    """Los dos cinturones, antes de servir nada.

    El primero es la banda de plausibilidad, que ataja el error de unidad. El segundo solo
    corre cuando el emisor publica su propia razón, y es el más fuerte que hay: si la nuestra
    y la suya discrepan, algo se leyó mal y da igual cuál de las dos esté bien.
    """
    if not (BANDA_PCT_PIB[0] <= pct <= BANDA_PCT_PIB[1]):
        raise DigepresError(
            f"{pct:.3f}% del PIB queda fuera de la banda {BANDA_PCT_PIB}: lo que falló es la "
            f"UNIDAD o la columna, no el país")
    if pct_emisor is None:
        return
    if not pct_emisor:
        return
    dif = abs(pct - pct_emisor) / pct_emisor * 100.0
    if dif > TOLERANCIA_CONTRA_EL_EMISOR_PCT:
        raise DigepresError(
            f"nuestra razón ({pct:.3f}%) y la que publica el emisor ({pct_emisor:.3f}%) "
            f"difieren {dif:.0f}%: se leyó mal una columna")


#: Rotulos del cuadro clasico, en su orden. Solo se usan cuando el emisor NO publica su %PIB,
#: que es el caso de los informes de 2008 a 2011.
_CLASICO = ("vigente", "ejecutado")


def unidad_de(texto: str) -> Optional[str]:
    """La unidad que el cuadro DECLARA en su encabezado, o `None` si no la declara.

    Nunca se adivina ni se elige la que hace cuadrar el resultado: entre el informe de 2009
    —millones— y el de 2010 —unidades de peso— hay un factor de mil, y elegir la que da una
    cifra plausible seria ajustar el metodo a la respuesta. Sin declaracion, se levanta.
    """
    n = _norm(texto)
    if "MILLONES" in n:
        return "millones"
    if re.search(r"\bEN\s+RD\$|VALORES\s+EN\s+RD\$|\(RD\$\)", n):
        return "unidades"
    return None


def leer_cuadro(palabras: Sequence[Dict[str, Any]], anio: int,
                pib_nominal: Optional[float] = None,
                unidad: str = "millones",
                lectura: str = "ejecutado") -> GastoFuncional:
    """La linea de Salud de una pagina ya extraida, con su razon contra el PIB.

    **Cuando el emisor publica su propio %PIB, se usa el suyo.** No es comodidad: el indicador
    ES una razon contra el PIB, asi que tomarla publicada evita elegir una columna de dinero
    —lo que exigiria acertar cual de diez es el devengado— y evita dividir por un PIB que
    puede venir de otra fuente y de otra aniada. La cifra del emisor y la nuestra no valen lo
    mismo y por eso `procedencia_de_la_razon` viaja con el dato.

    Solo cuando no la publica se computa, y ahi corren los dos cinturones de `verificar`.
    """
    filas = lineas_de(palabras)
    fila = fila_salud(filas)
    if not fila:
        raise DigepresError(
            f"{anio}: la pagina no trae una fila cuyo rotulo sea exactamente «Salud». O no es "
            f"el cuadro funcional, o el emisor cambio como la rotula.")
    del_emisor = leer_pct_pib_del_emisor(filas)
    if del_emisor is not None:
        verificar(del_emisor, None)
        return GastoFuncional(anio=anio, pct_pib=del_emisor,
                              procedencia_de_la_razon="emisor",
                              pct_pib_del_emisor=del_emisor)

    numeros = [v for v in (_numero(t) for _, t in fila) if v is not None]
    if len(numeros) < len(_CLASICO):
        raise DigepresError(
            f"{anio}: la fila de Salud trae {len(numeros)} numeros y el cuadro clasico tiene "
            f"{len(_CLASICO)} columnas de monto mas el porcentaje de ejecucion")
    monto = numeros[_CLASICO.index(lectura)]
    if pib_nominal is None:
        raise DigepresError(
            f"{anio}: el cuadro no publica su %PIB, asi que hace falta el PIB nominal para "
            f"computarlo. Servir el monto suelto seria servir otra magnitud.")
    pct = razon_contra_pib(monto, unidad, pib_nominal)
    verificar(pct, None)
    return GastoFuncional(anio=anio, pct_pib=round(pct, 3),
                          procedencia_de_la_razon="computado",
                          monto=monto, unidad_del_monto=unidad)


def paginas_del_cuadro(pdf) -> List[int]:  # pragma: no cover - I/O de PDF
    """Indices de las paginas cuyo texto trae el rotulo del cuadro funcional."""
    return [i for i, p in enumerate(pdf.pages)
            if ROTULO_CUADRO in _norm(p.extract_text() or "")]


def informes_por_anio() -> Dict[int, str]:  # pragma: no cover - red
    """`{anio: url}` de los informes anuales, desde la biblioteca de medios del emisor.

    Su pagina de informes NO sirve: los botones de los aniios viejos apuntan a documentos de
    otra serie —el de 2009 entrega la Ley de Presupuesto de 2012— y los recientes son
    acordeones que arma el navegador. La biblioteca de medios es la unica via que devuelve el
    archivo real, y esto queda escrito porque deducirlo costo una tarde.
    """
    import httpx

    fuera = re.compile(r"Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|"
                       r"Octubre|Noviembre|Diciembre|Medio-Termino|Glosario|Formulacion|"
                       r"Fisica", re.I)
    sirve = re.compile(r"Informe.*Ejecucion.*Presupuestaria", re.I)
    out: Dict[int, str] = {}
    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": "sdq-mip/1.0"}) as c:
        for pagina in range(1, 9):
            r = c.get(MEDIA_API, params={"search": "ejecucion", "per_page": 100,
                                         "page": pagina})
            if r.status_code != 200:
                break
            lote = r.json()
            if not isinstance(lote, list) or not lote:
                break
            for m in lote:
                u = str(m.get("source_url") or "")
                n = u.rsplit("/", 1)[-1]
                if not n.lower().endswith(".pdf") or fuera.search(n) or not sirve.search(n):
                    continue
                anio = re.search(r"((?:19|20)\d\d)", n)
                if anio:
                    out.setdefault(int(anio.group(1)), u)
    if not out:
        raise DigepresError(
            "la biblioteca de medios no devolvio ningun informe anual: o cambio el contrato, "
            "o cambio como el emisor nombra sus archivos")
    return out


def leer_informe(contenido: bytes, anio: int,
                 pib_nominal: Optional[float] = None,
                 lectura: str = "ejecutado") -> GastoFuncional:
    """La linea de Salud del informe de un anio, eligiendo pagina y unidad por su contenido.

    Recorre las paginas que traen el rotulo del cuadro y se queda con la PRIMERA que produce
    una lectura que pasa los guards. No es «probar hasta que salga»: cada intento tiene que
    pasar la banda de plausibilidad, asi que una pagina de prosa que menciona el rotulo no
    puede colarse — no tiene fila de Salud, o sus numeros no dan una razon creible.

    Si ninguna pagina sirve, se levanta con los motivos acumulados. Devolver `None` dejaria al
    llamador sin saber si el emisor cambio el cuadro o si el anio no existe.
    """
    import io

    import pdfplumber

    motivos: List[str] = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for i in paginas_del_cuadro(pdf):
            pagina = pdf.pages[i]
            unidad = unidad_de(pagina.extract_text() or "")
            if unidad is None:
                motivos.append(f"p{i}: el cuadro no declara su unidad")
                continue
            try:
                return leer_cuadro(pagina.extract_words(x_tolerance=1.2, y_tolerance=2),
                                   anio, pib_nominal, unidad, lectura)
            except DigepresError as e:
                motivos.append(f"p{i}: {e}")
    raise DigepresError(
        f"{anio}: ninguna pagina con el cuadro funcional dio una lectura valida. "
        + " · ".join(motivos[:4]))
