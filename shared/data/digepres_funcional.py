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

#: Como rotula el emisor el cuadro. Se busca normalizado —sin tildes y en mayusculas— y hay
#: que aceptar las DOS familias: los informes anuales dicen «Clasificacion Funcional» y los
#: libros de presupuesto ejecutado titulan «Ejecucion Funcional del Gasto». Buscar solo la
#: primera dejaba fuera justo la tabla buena del libro —la que trae las ocho columnas y cierra
#: sus identidades— y hacia caer el ano entero en la tabla por objeto o en nada.
ROTULOS_CUADRO = ("CLASIFICACION FUNCIONAL", "EJECUCION FUNCIONAL")
ROTULO_CUADRO = ROTULOS_CUADRO[0]

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
    #: Que forma de cuadro cerro su identidad: `funcional` o `por_objeto`.
    layout: Optional[str] = None


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


def numeros_de(pegadas: Sequence[Tuple[float, str]]) -> List[float]:
    """Los numeros de la fila, SIN el codigo de funcion que la abre.

    «4.2» y «223» son codigos del clasificador, no cifras, y colarlos costo la tabla por
    objeto entera: como valen menos que `UMBRAL_MONTO` entraban como porcentaje, la rama que
    suma los objetos contra el total exige que NO haya porcentajes, y el ano se perdia
    diciendo que ninguna identidad cerraba. `rotulo_de` ya los saltaba para el rotulo; la
    fila tenia que saltarlos tambien.
    """
    solo_codigo = re.compile(r"^[\d.]+$")
    solo_guion = re.compile(r"^[\s\u00ad\u2010-\u2015-]+$")
    out: List[float] = []
    empezo_el_rotulo = False
    for _, t in pegadas:
        if not empezo_el_rotulo and (solo_codigo.match(t) or solo_guion.match(t)):
            continue
        empezo_el_rotulo = True
        v = _numero(t)
        if v is not None:
            out.append(v)
    return out


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


def xs_de_columna(filas: Sequence[Sequence[Dict[str, Any]]], rotulo: str,
                  hasta: Optional[int] = None) -> List[float]:
    """TODAS las coordenadas donde aparece ese encabezado, de izquierda a derecha.

    Plural a proposito. El informe anual pone el ano ANTERIOR a la izquierda para comparar y
    el ano del informe a la derecha, asi que el encabezado «%PIB» aparece DOS veces: la
    version anterior de esta funcion devolvia la primera y publicaba la razon del ano
    equivocado. En 2015 las dos daban 1,9 y el defecto era invisible.
    """
    objetivo = _norm(rotulo)
    xs: List[float] = []
    for k, ws in enumerate(filas):
        if hasta is not None and k >= hasta:
            break
        for w in ws:
            t = _norm(w["text"])
            if t == objetivo or (objetivo in ("PIB", "%PIB") and _RX_ENCABEZADO_PIB.match(t)):
                xs.append(float(w["x0"]))
    return sorted(xs)


def x_de_columna(filas: Sequence[Sequence[Dict[str, Any]]], rotulo: str,
                 hasta: Optional[int] = None) -> Optional[float]:
    """Coordenada del encabezado pedido, buscando solo por ENCIMA de los datos.

    Las columnas se leen por su rotulo y no por su indice: un cuadro que agrega una columna
    corre todas las demas, y leer por posicion serviria la variacion donde se espera el
    devengado. Y se busca acotado, porque la palabra «PIB» aparece tambien en la prosa que
    rodea al cuadro — en el informe de 2018 hay tres parrafos que la usan antes de la tabla.
    """
    xs = xs_de_columna(filas, rotulo, hasta)
    # La ULTIMA: el bloque del ano que el informe trata va a la derecha del comparativo.
    return xs[-1] if xs else None


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


#: Cuanto queda nuestro computo por DEBAJO del %PIB que publica el emisor, medido el
#: 2026-08-23 en los CUATRO anios en que las dos cifras existen: 2014 6,6% · 2015 7,7% ·
#: 2016 6,0% · 2018 7,1%. Un sesgo del mismo signo cuatro veces no es ruido de lectura: es
#: que el emisor dividio por el PIB de su anada y las cuentas nacionales se rebasaron a 2018.
#: Queda escrito para que el dia que el contraste se dispare se sepa contra que se compara.
SESGO_MEDIDO_CONTRA_EL_EMISOR_PCT = (6.0, 7.7)


def verificar(pct: float, pct_emisor: Optional[float]) -> None:
    """Los dos cinturones, antes de servir nada.

    El primero es la banda de plausibilidad, que ataja el error de unidad. El segundo solo
    corre cuando el emisor publica su propia razón, y es el más fuerte que hay: si la nuestra
    y la suya discrepan MAS de lo que explica la anada del denominador, algo se leyó mal y da
    igual cuál de las dos esté bien. Por eso la tolerancia es holgada y esta medida, no
    elegida: tiene que dejar pasar el sesgo de `SESGO_MEDIDO_CONTRA_EL_EMISOR_PCT` y frenar
    lo que no sea eso — leer la columna del ano anterior, por ejemplo, que en 2016 habria
    dado 1,7 contra 1,6 y cae dentro, pero en 2018 da 2,0 contra 1,86.
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


#: El universo que la ley fija y que la pagina tiene que DECLARAR. El mismo emisor publica el
#: gasto del Gobierno General Nacional con el mismo cuadro y la misma forma, y para 2022 da
#: RD$117,5 mil millones donde el Gobierno Central da otra cifra: confundirlos no rompe nada,
#: cambia de sujeto. Se lee del ENCABEZADO de la pagina, nunca del nombre del archivo — el
#: libro rotulado «GGN» trae adentro la seccion del Gobierno Central, y descartarlo por su
#: nombre habria tirado un ano bueno.
UNIVERSO = "GOBIERNO CENTRAL"

#: Debajo de esto un numero de la fila no es dinero sino un porcentaje. El gasto en salud no
#: baja de mil en ninguna de las dos unidades en que el emisor publica el cuadro, y los
#: porcentajes que trae —ejecucion, participacion, %PIB, variacion— no pasan de tres cifras.
UMBRAL_MONTO = 1000.0

#: Cuanto puede fallar una identidad del cuadro para seguir considerandose cerrada.
TOLERANCIA_IDENTIDAD_PCT = 0.5

#: El emisor imprime los porcentajes con un decimal, asi que dos columnas distintas solo se
#: distinguen si se exige coincidencia ABSOLUTA fina: en el libro de 2019 el comprometido da
#: 96,5% y el devengado 96,0%, y una tolerancia relativa del 0,5% se los come a los dos.
TOLERANCIA_PORCENTAJE_IMPRESO = 0.1


def _cierra(a: float, b: float) -> bool:
    if not b:
        return abs(a) < 1.0
    return abs(a - b) / abs(b) * 100.0 <= TOLERANCIA_IDENTIDAD_PCT


def devengado_de(numeros: Sequence[float]) -> Tuple[float, str]:
    """El monto EJECUTADO de la fila, elegido por las identidades del cuadro.

    No por posicion y no por encabezado, que fue como fallaron las dos versiones anteriores:
    el cuadro cambia de forma cinco veces entre 2009 y 2022 —tres columnas en el informe
    clasico, ocho en el libro, once en el informe comparativo que ademas repite el ano
    anterior— y cualquier regla posicional sirve la columna de al lado sin que nada avise.

    Las identidades son del propio cuadro y no se pueden fingir:

    * **por objeto**: la suma de los objetos de gasto da el total, y ese total ES el
      devengado — comprobado contra los libros de 2017 y 2019, donde la misma obra trae las
      dos tablas y el total por objeto coincide al peso con el devengado funcional;
    * **funcional**: devengado / vigente = el % de ejecucion que el cuadro imprime.

    Y la identidad hace de guard sola: el libro de 2013 trae DOS tablas por objeto y en una
    la suma da el doble del total —es otra apertura del mismo gasto—, asi que esa pagina no
    cierra y se descarta sin que haya que saber de antemano cual era.
    """
    montos = [v for v in numeros if abs(v) >= UMBRAL_MONTO]
    pcts = [v for v in numeros if abs(v) < UMBRAL_MONTO]
    if len(montos) < 2:
        raise DigepresError(
            f"la fila trae {len(montos)} montos: no alcanza para cerrar ninguna identidad "
            f"del cuadro, asi que no hay forma de saber cual columna es el devengado")

    if not pcts and _cierra(sum(montos[:-1]), montos[-1]):
        return montos[-1], "por_objeto"

    candidatos = set()
    for vigente in montos:
        if not vigente:
            continue
        for ejecutado in montos:
            if ejecutado is vigente:
                continue
            for p in pcts:
                if not 50.0 <= p <= 120.0:
                    continue
                if abs(ejecutado / vigente * 100.0 - p) <= TOLERANCIA_PORCENTAJE_IMPRESO:
                    candidatos.add(round(ejecutado, 1))
    if len(candidatos) == 1:
        return candidatos.pop(), "funcional"
    if not candidatos:
        raise DigepresError(
            "ninguna pareja de columnas reproduce el % de ejecucion que el cuadro imprime: "
            "o no es el cuadro funcional, o el emisor dejo de publicar el porcentaje")
    raise DigepresError(
        f"{len(candidatos)} columnas distintas cierran el % de ejecucion {sorted(candidatos)}: "
        f"la fila es ambigua y elegir una seria adivinar")


def unidad_de(texto: str) -> Optional[str]:
    """La unidad que el cuadro DECLARA en su encabezado, o `None` si no la declara.

    Nunca se adivina ni se elige la que hace cuadrar el resultado: entre el informe de 2009
    —millones— y el de 2010 —unidades de peso— hay un factor de mil, y elegir la que da una
    cifra plausible seria ajustar el metodo a la respuesta. Sin declaracion, se levanta.
    """
    n = _norm(texto)
    if "MILLONES" in n:
        return "millones"
    if re.search(r"\bEN\s+RD\$|VALORES\s+(EN\s+)?RD\$|\(RD\$\)", n):
        return "unidades"
    return None


def leer_cuadro(palabras: Sequence[Dict[str, Any]], anio: int,
                pib_nominal: Optional[float] = None,
                unidad: str = "millones") -> GastoFuncional:
    """La linea de Salud de una pagina ya extraida, con su razon contra el PIB.

    **La razon se COMPUTA siempre que se pueda, aunque el emisor publique la suya.** Es lo
    contrario de lo que decidi al escribir este modulo, y lo que lo dio vuelta es una
    medicion: en los cuatro anios en que el emisor publica su %PIB, nuestro computo queda
    entre 6,0% y 7,7% por DEBAJO del suyo, siempre en el mismo sentido. Un sesgo de un solo
    signo en cuatro anios no es error de lectura: el emisor dividio por el PIB de su anada y
    las cuentas nacionales se rebasaron despues a 2018, que subio el denominador.

    Servir la cifra del emisor donde la publica y la nuestra donde no, que era el diseno
    anterior, arma una serie cosida con DOS denominadores — y el salto de 2011 a 2015 seria
    un artefacto de quien hizo la division, no gasto publico. Se computa todo contra una sola
    serie de PIB, y la del emisor queda como CONTRASTE con su sesgo declarado.
    """
    filas = lineas_de(palabras)
    fila = fila_salud(filas)
    if not fila:
        raise DigepresError(
            f"{anio}: la pagina no trae una fila cuyo rotulo sea exactamente «Salud». O no es "
            f"el cuadro funcional, o el emisor cambio como la rotula.")
    del_emisor = leer_pct_pib_del_emisor(filas)
    numeros = numeros_de(fila)

    if pib_nominal is None:
        if del_emisor is None:
            raise DigepresError(
                f"{anio}: no hay PIB nominal para computar la razon y el cuadro tampoco "
                f"publica la suya. Servir el monto suelto seria servir otra magnitud.")
        verificar(del_emisor, None)
        return GastoFuncional(anio=anio, pct_pib=del_emisor,
                              procedencia_de_la_razon="emisor",
                              pct_pib_del_emisor=del_emisor)

    monto, layout = devengado_de(numeros)
    pct = razon_contra_pib(monto, unidad, pib_nominal)
    verificar(pct, del_emisor)
    return GastoFuncional(anio=anio, pct_pib=round(pct, 3),
                          procedencia_de_la_razon="computado",
                          monto=monto, unidad_del_monto=unidad,
                          pct_pib_del_emisor=del_emisor, layout=layout)


#: Que documento sirve cada anio, DECLARADO. Se probaron los cuatro caminos automaticos y
#: los cuatro fallan: el nombre del archivo no dice el universo —el libro «GGN 2022» trae
#: adentro la seccion del Gobierno Central y es el unico documento de ese anio—, el emisor
#: publica cuatro familias distintas que se llaman casi igual, y la que suena mas obvia es
#: justamente la que NO hay que usar. La lista es corta y la evidencia de cada linea vale mas
#: que una expresion regular que ya se equivoco dos veces.
#:
#: **El «Informe de Ejecucion Presupuestaria» solo sirve hasta 2011.** Desde 2015 su cuadro
#: arrastra el anio anterior en las columnas de la izquierda —incluida una segunda columna de
#: %PIB— y en 2018 la cifra que publica es el presupuesto VIGENTE, no el devengado: da
#: RD$78,2 mil millones donde el libro da 69,0. Con el informe la trayectoria 2017-2019 es un
#: pico y una caida que no existieron.
#:
#: Los anios que se cruzan entre las dos familias coinciden al peso: 2011 da 37.380.292.749
#: en las dos, y el devengado de 2014 del libro es exactamente la columna de comparacion del
#: informe de 2015.
DOCUMENTOS = {
    2009: "Informe-de-Ejecucion-Presupuestaria-2009-DIGEPRES.pdf",
    2010: "Informe-de-Ejecucion-Presupuestaria-2010-DIGEPRES.pdf",
    2011: "Libro-Presupuesto-Ejecutado-2011-TomoI.pdf",
    2012: "Libro-Presupuesto-Ejecutado-2012.pdf",
    2013: "Libro-Presupuesto-Ejecutado-2013.pdf",
    2014: "Libro-Presupuesto-Ejecutado-2014-TomoI.pdf",
    2015: "Libro-Presupuesto-Ejecutado-2015-TomoI.pdf",
    2016: "Libro-Presupuesto-Ejecutado-2016-TomoI.pdf",
    2017: "Libro-Presupuesto-Ejecutado-2017-TomoI.pdf",
    2018: "Libro-Presupuesto-Ejecutado-2018-TomoI.pdf",
    2019: "Libro-Presupuesto-Ejecutado-2019-TOMO1.pdf",
    2021: "libro_ejecucion_2021.pdf",
    2022: "Libro-Presupuesto-Ejecutado-GGN-2022.pdf",
}

#: Los anios que DIGEPRES no publica con este cuadro, buscados uno por uno el 2026-08-23.
#:
#: ══ 2026-08-24 ══ **Ya NO son huecos del indicador.** La hoja COFOG del Ministerio de
#: Hacienda (`shared.data.hacienda_cofog`) trae 2008-2025 completo, incluidos 2020 y 2025,
#: que son metas de la ley. Esta lista pasa a describir lo que le falta a ESTA fuente, que
#: quedo de contraste — no lo que le falta al 2.33. La distincion importa: leida como antes,
#: decia que dos metas eran inmedibles y ya no lo son.
SIN_CUADRO_FUNCIONAL = {
    2020: ("el «Libro de Ejecucion 2020» es un informe narrativo de 53 paginas y el de 516 "
           "es de empresas publicas; el consolidado del SPNF de ese anio no trae la seccion "
           "del Gobierno Central con la fila de Salud"),
    2023: "ni el libro de ejecucion ni el consolidado del SPNF traen el cuadro funcional",
    2024: "idem 2023; el libro de ejecucion de ese anio es de gobiernos LOCALES",
    2025: "el ejercicio no tiene todavia libro de presupuesto ejecutado",
}


def paginas_del_cuadro(pdf) -> List[int]:  # pragma: no cover - I/O de PDF
    """Indices de las paginas cuyo texto trae el rotulo del cuadro funcional."""
    return [i for i, p in enumerate(pdf.pages)
            if any(r in _norm(p.extract_text() or "") for r in ROTULOS_CUADRO)]


def url_del_documento(nombre: str) -> str:  # pragma: no cover - red
    """La URL real de un documento del emisor, por su biblioteca de medios.

    Su pagina de informes NO entrega el archivo: los botones de los anios viejos apuntan a
    documentos de otra serie —el de 2009 sirve la Ley de Presupuesto de 2012, comprobado
    abriendo el PDF— y las tarjetas recientes son acordeones que arma el navegador. Esto
    queda escrito porque deducirlo costo una tarde.
    """
    import httpx

    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": "sdq-mip/1.0"}) as c:
        r = c.get(MEDIA_API, params={"search": nombre.replace(".pdf", ""), "per_page": 60})
        r.raise_for_status()
        for m in r.json():
            u = str(m.get("source_url") or "")
            if u.rsplit("/", 1)[-1] == nombre:
                return u
    raise DigepresError(
        f"la biblioteca de medios no tiene «{nombre}»: o el emisor lo renombro, o lo bajo")


def informes_por_anio() -> Dict[int, str]:  # pragma: no cover - red
    """`{anio: url}` de los documentos declarados en `DOCUMENTOS`."""
    return {anio: url_del_documento(n) for anio, n in sorted(DOCUMENTOS.items())}


def leer_documento(fuente, anio: int,
                   pib_nominal: Optional[float] = None) -> GastoFuncional:  # pragma: no cover
    """La linea de Salud de un documento, eligiendo pagina y unidad por su CONTENIDO.

    `fuente` es una ruta en disco o un objeto de archivo. **Nunca los bytes.** El libro del
    emisor pesa entre 28 y 66 MB y tiene hasta 980 paginas: sostener el contenido en memoria
    mientras el parser arma sus objetos de pagina fue lo que mato al proceso en produccion el
    2026-08-24 —murio sin traza, que es la firma del sistema matando por memoria— despues de
    leer bien seis anios. Por eso se abre desde el disco y por eso cada pagina se libera
    apenas se descarta: el pico queda plano y no depende de cuantos anios lleve la corrida.

    Recorre las paginas y se queda con la PRIMERA que produce una lectura que pasa los
    guards. No es «probar hasta que salga»: cada intento tiene que declarar su universo,
    declarar su unidad, traer una fila de Salud y cerrar una identidad del cuadro.

    Si ninguna sirve, LEVANTA con los motivos acumulados. Devolver `None` dejaria al llamador
    sin saber si el emisor cambio el cuadro o si el anio no existe.
    """
    import pdfplumber

    motivos: List[str] = []
    with pdfplumber.open(fuente) as pdf:
        for i, pagina in enumerate(pdf.pages):
            try:
                texto = _norm(pagina.extract_text() or "")
                if not any(r in texto for r in ROTULOS_CUADRO):
                    continue
                if UNIVERSO not in texto:
                    motivos.append(f"p{i}: la pagina no declara «{UNIVERSO}»")
                    continue
                unidad = unidad_de(texto)
                if unidad is None:
                    motivos.append(f"p{i}: el cuadro no declara su unidad")
                    continue
                try:
                    return leer_cuadro(pagina.extract_words(x_tolerance=1.2, y_tolerance=2),
                                       anio, pib_nominal, unidad)
                except DigepresError as e:
                    motivos.append(f"p{i}: {e}")
            finally:
                # Sin esto el parser se queda con los objetos de CADA pagina recorrida y un
                # libro de 900 paginas no entra en la memoria de un contenedor web.
                pagina.flush_cache()
    raise DigepresError(
        f"{anio}: ninguna pagina con el cuadro funcional dio una lectura valida. "
        + " · ".join(motivos[:6]))


def leer_informe(contenido: bytes, anio: int,
                 pib_nominal: Optional[float] = None) -> GastoFuncional:  # pragma: no cover
    """Igual que `leer_documento` pero desde bytes. **No usar en un proceso servidor**: es
    justamente el camino que quedarse con los bytes en memoria hace caro. Existe para sondas
    y scripts, donde el archivo ya esta en la mano."""
    import io

    return leer_documento(io.BytesIO(contenido), anio, pib_nominal)
