"""SECMCA / EMFA — Estadísticas Monetarias y Financieras Armonizadas del CMCA.

Crédito al sector privado por destino económico y tasas de interés bancarias, para las
plazas de Centroamérica, Panamá y República Dominicana. Es la ÚNICA fuente armonizada del
boletín regional: la propia SECMCA declara que sus otros indicadores bancarios no lo están.

**No trae prudenciales, y no es un descuido nuestro.** Se recorrieron las 520 variables de
los 5 temas de EMFA con un filtro de vocabulario prudencial
(`moros|solvenc|adecuac|vencid|rentabil|ROA|ROE|patrimon|provisi`): las 38 coincidencias son
todas «capital» en sentido contable de balance —«Total pasivos y capital», «Fondos aportados
por los propietarios»—, nunca adecuación de capital regulatorio. Solvencia y morosidad hay
que traerlas supervisor por supervisor.

**Por qué se leen archivos y no el API.** `secmca-api.secmca.org` publica sus catálogos sin
credencial, pero TODO endpoint que devuelve valores responde 401 «No tiene permisos para
consumir este recurso». Verificado el 2026-09-04 sobre las 44 rutas que declara su OpenAPI,
con y sin cabeceras de navegador, y ejecutando `fetch()` desde el propio origen con cookies.
El portal público de SECMCA obtiene sus datos a través de un plugin de WordPress que guarda
la credencial del lado del servidor. Los cuadros de esta página, en cambio, son archivos
PUBLICADOS para descarga: se leen como lo que son.
"""
import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.secmca")

EMFA_PAGE = "https://www.secmca.org/emfa/"

#: Prefijo del archivo → ISO3. El nombre del archivo es la única marca de país que traen.
PREFIJO_ISO3 = {"CR": "CRI", "ES": "SLV", "GT": "GTM", "HN": "HND",
                "NC": "NIC", "RD": "DOM", "PA": "PAN"}

#: Belice pertenece al CMCA pero NO publica cuadro EMFA. Se declara para que su ausencia
#: sea un hecho registrado y no un país que alguien "olvidó" en la lista.
SIN_CUADRO_PUBLICADO = {"BLZ": "el CMCA no publica cuadro EMFA de Belice"}

_ARCHIVO_RE = re.compile(
    r"/wp-content/uploads/\d{4}/\d{2}/([A-Z]{2})_CMCA_EMFA_2_DIV\.xls", re.IGNORECASE)

#: Qué cuadro es cada hoja, por su TÍTULO INTERNO — nunca por el nombre de la hoja ni por
#: el Índice. Las tres vías se probaron sobre los siete archivos y solo esta sobrevive:
#:
#:  · El nombre de hoja cambia por país: la tasa activa es `IV.4.TIbancactMN` en RD,
#:    `V.4TIbancactMN` en Costa Rica y `IV.4.Tasas banca activas en MN` en Panamá.
#:  · El Índice trae hipervínculos a cada hoja y parecía el diccionario ideal, pero en el
#:    archivo de RD **15 de sus 19 enlaces apuntan a hojas que no existen** —quedaron con
#:    los nombres de la convención de Costa Rica—. Un conector que confiara en él serviría
#:    tasas bajo la etiqueta de un balance, en silencio, justo en el país central del
#:    boletín.
#:
#: El `1/` intercalado es una marca de nota al pie que varios emisores meten en mitad del
#: título («TASAS DE INTERÉS BANCARIAS1/ SOBRE PRÉSTAMOS»): por eso los patrones no exigen
#: que las palabras sean contiguas.
CUADROS: Dict[str, re.Pattern] = {
    "credito_osd_privado_mn": re.compile(
        r"PR[EÉ]STAMOS\s+DE\s+LAS\s+OTRAS\s+SOCIEDADES\s+DE\s+DEP[OÓ]SITO.*"
        r"(SECTOR\s+PRIVADO|PRINCIPALES)", re.I | re.S),
    "tasa_activa_mn": re.compile(
        r"TASAS\s+DE\s+INTER[EÉ]S\s+BANCARIAS\S*\s+SOBRE\s+PR[EÉ]STAMOS", re.I),
    "tasa_pasiva_mn": re.compile(
        r"TASAS\s+DE\s+INTER[EÉ]S\s+BANCARIAS\S*\s+PASIVAS", re.I),
}

#: Solo moneda nacional en la edición 1: en ME la cobertura es despareja y en las plazas
#: dolarizadas la distinción no significa lo mismo.
_ES_MONEDA_NACIONAL = re.compile(r"MONEDA\s+NACIONAL|\bEN\s+MN\b|\bEN\s+MN\d", re.I)

#: Los emisores mezclan español e inglés dentro de un mismo cuadro —el de tasas de RD trae
#: «Apr» entre «Mar» y «May»—, así que las dos lenguas van en el mapa. Sin «apr», «aug» y
#: «dec» esas filas se perdían enteras y en silencio.
_MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
          "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
          "jan": 1, "apr": 4, "aug": 8, "dec": 12}

#: Lo que los emisores escriben donde no hay dato. Va a `None`: un ausente no es un cero,
#: y en una tasa el cero es una afirmación fuerte y falsa.
_AUSENTES = {"n.a", "n.a.", "na", "n/a", "nd", "n.d", "n.d.", "-", "--", "...", ""}


def discover_country_files(html: str) -> Dict[str, str]:
    """``{iso3: url}`` de los cuadros EMFA enlazados en *html*.

    Las URLs llevan el año y mes de subida (`/uploads/2026/08/RD_...`), así que cambian en
    cada actualización: se descubren de la página, nunca se fijan en el código.
    """
    fuera: Dict[str, str] = {}
    for m in _ARCHIVO_RE.finditer(html):
        iso3 = PREFIJO_ISO3.get(m.group(1).upper())
        if iso3:
            url = m.group(0)
            fuera[iso3] = url if url.startswith("http") else "https://www.secmca.org" + url
    return fuera


def titulo_de_hoja(filas: List[List]) -> str:
    """El título del cuadro: el primer texto largo de las primeras filas.

    Se lee del cuerpo de la hoja y no de su nombre porque es lo único que describe el
    contenido REAL de esa hoja en los siete archivos.
    """
    for fila in filas[:12]:
        for celda in fila[:3]:
            texto = str(celda).strip()
            if len(texto) > 25:
                return texto
    return ""


def clasificar_hoja(titulo: str) -> Optional[str]:
    """Qué cuadro de `CUADROS` es este título, o ``None`` si no es uno de los nuestros.

    Excluye los cuadros en moneda extranjera: el título del de préstamos y el de tasas se
    parecen mucho, y lo único que los separa es la moneda.
    """
    if not titulo or not _ES_MONEDA_NACIONAL.search(titulo):
        return None
    # El orden importa: «TASAS ... SOBRE PRÉSTAMOS» también contiene «PRÉSTAMOS», así que
    # las tasas se prueban primero y el crédito solo se acepta si ninguna tasa coincidió.
    for clave in ("tasa_activa_mn", "tasa_pasiva_mn"):
        if CUADROS[clave].search(titulo):
            return clave
    if CUADROS["credito_osd_privado_mn"].search(titulo):
        return "credito_osd_privado_mn"
    return None


def _fin_de_mes(anio: int, mes: int) -> date:
    if mes == 12:
        return date(anio, 12, 31)
    return date(anio, mes + 1, 1) - timedelta(days=1)


def parse_periodo(a: object, b: object,
                  anio_arrastrado: Optional[int] = None) -> Optional[date]:
    """``(2001.0, "Dic")``, ``("01", "Dic-01")`` o una fecha → el CORTE del mes.

    Los emisores escriben el período de tres formas distintas y hay que soportarlas todas,
    porque **cambian dentro de un mismo archivo**: el cuadro de préstamos de Costa Rica
    empieza con año y mes en texto y a partir de 2016 pasa a fechas de Excel. Leyendo solo
    la primera forma, Costa Rica terminaba en 2015 y se perdían diez años sin un error —
    la serie simplemente se cortaba.

    Devuelve ``None`` cuando la fila no es una observación (encabezado, nota al pie).
    """
    # Ya resuelta por el lector (celda con formato de fecha).
    for celda in (a, b):
        if isinstance(celda, date):
            return _fin_de_mes(celda.year, celda.month)

    texto_b = str(b or "").strip()
    # La celda de un mes es corta y empieza por el mes («Dic», «Ene», «Dic-01», «Sept»).
    # Sin esta cota, el nombre de un mes escondido dentro de una nota al pie —y el año
    # arrastrado desde arriba— fabricaba una observación: el cuadro de tasas de RD daba un
    # corte a diciembre de 2026, tres meses en el FUTURO, desde una línea de notas.
    if len(texto_b) > 10:
        return None
    m_mes = re.match(r"(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic|jan|apr|aug|dec)",
                     texto_b, re.I)
    if not m_mes:
        return None
    mes = _MESES[m_mes.group(1).lower()]

    anio: Optional[int] = None
    m_pegado = re.search(r"-(\d{2,4})\s*$", texto_b)          # "Dic-01"
    if m_pegado:
        anio = int(m_pegado.group(1))
    else:
        texto_a = str(a or "").strip()
        m_a = re.match(r"^(\d{2,4})(?:\.0)?$", texto_a)        # 2001.0 · "01"
        if m_a:
            anio = int(m_a.group(1))
    if anio is None:
        # El año se escribe UNA vez y los once meses siguientes dejan la celda vacía.
        # Sin arrastrarlo se reconoce una fila de cada doce: Guatemala entregaba 26
        # observaciones de 300 y Nicaragua 19, y las dos parecían fuentes pobres en vez
        # de un parser que leía mal.
        anio = anio_arrastrado
    if anio is None:
        return None
    if anio < 100:                                             # "01" → 2001, "97" → 1997
        anio += 2000 if anio < 70 else 1900
    if not (1990 <= anio <= date.today().year + 1):
        return None
    return _fin_de_mes(anio, mes)


def parse_valor(celda: object) -> Optional[float]:
    """El número de la celda, o ``None``. Nunca cero por defecto."""
    if isinstance(celda, bool):
        return None
    if isinstance(celda, (int, float)):
        return float(celda)
    texto = str(celda).strip().lower()
    if texto in _AUSENTES:
        return None
    # La coma es decimal o de miles según el emisor, y confundirlas multiplica por cien una
    # tasa real. Se decide por la forma: una sola coma con una o dos cifras detrás y sin
    # punto es decimal («3,09»); en cualquier otro caso es separador de miles («1,234,567»).
    if texto.count(",") == 1 and "." not in texto and len(texto.split(",")[1]) in (1, 2):
        texto = texto.replace(",", ".")
    else:
        texto = texto.replace(",", "")
    try:
        return float(texto)
    except ValueError:
        return None


def etiquetas_de_columna(filas: List[List], fila_datos: int, ncols: int,
                         primera_col: int = 2) -> Dict[int, str]:
    """``{índice de columna: etiqueta}`` juntando los niveles de encabezado.

    Los cuadros traen el encabezado repartido en varias filas —«Consumo» arriba y «Tarjeta
    de Crédito» debajo—, así que la etiqueta de una columna es la concatenación de lo que
    haya sobre ella. Una columna sin ninguna etiqueta NO se inventa: se omite, y su dato no
    entra. Publicar un valor sin saber de qué es sería peor que no publicarlo.
    """
    cabecera = filas[max(0, fila_datos - 6):fila_datos]

    # El rótulo de un grupo se escribe UNA vez, en la primera columna del grupo (celdas
    # combinadas), así que se propaga a la derecha hasta que aparece otro. Sin esto,
    # «Operaciones nuevas · Ahorro» y «Saldos vivos · Ahorro» colapsaban los dos en
    # «Ahorro»: dos mediciones distintas con la misma clave, que la base rechaza y —peor—
    # que sin la restricción se habrían pisado en silencio.
    extendidas: List[List[str]] = []
    for fila in cabecera:
        vistos: List[str] = [""] * primera_col
        ultimo = ""
        # Arranca a la DERECHA del período: el título del cuadro vive en las primeras
        # columnas y, propagado, se colaba dentro de cada etiqueta («TASAS DE INTERÉS
        # BANCARIAS … · Construcción»), que además de ruido volvía la clave dependiente
        # de cómo el emisor titula la hoja.
        for col in range(primera_col, ncols):
            texto = str(fila[col]).strip() if col < len(fila) else ""
            # `(1)`, `1/` y demás son marcas de nota al pie, no nombres de columna.
            if texto and re.fullmatch(r"[\(\)\d/\.\s]+", texto):
                texto = ""
            if texto:
                ultimo = texto
            vistos.append(ultimo)
        extendidas.append(vistos)

    etiquetas: Dict[int, str] = {}
    for col in range(primera_col, ncols):            # a la derecha del período
        partes: List[str] = []
        for fila in extendidas:
            texto = fila[col]
            if texto and texto not in partes:
                partes.append(texto)
        if partes:
            etiquetas[col] = " · ".join(partes)

    # Si dos columnas terminan con la MISMA etiqueta, esa etiqueta no las identifica y
    # ninguna se puede publicar: son mediciones distintas y no hay forma de decir cuál es
    # cuál. Se descartan las dos y queda constancia. Quedarse con una sería elegir al azar
    # y presentarlo como un hecho; nombrarlas por su posición («columna 13») daría una
    # clave que nadie puede leer en un boletín.
    repetidas = {e for e in etiquetas.values()
                 if list(etiquetas.values()).count(e) > 1}
    if repetidas:
        logger.warning("[SECMCA] %d columna(s) sin etiqueta que las distinga, descartadas: %s",
                       sum(1 for v in etiquetas.values() if v in repetidas),
                       sorted(repetidas)[:3])
        etiquetas = {c: e for c, e in etiquetas.items() if e not in repetidas}
    return etiquetas


#: Techo de una tasa bancaria creíble, en PORCENTAJE. Una activa de tarjeta ronda el 60% y
#: ninguna plaza de la región publica tres dígitos: por encima de esto, la normalización se
#: equivocó y es preferible no publicar a publicar un número cien veces mal.
TASA_MAXIMA_CREIBLE_PCT = 150.0

#: Por debajo de esto, el grupo entero está expresado como FRACCIÓN (0,186 = 18,6%). El
#: umbral va en 1,5 y no en 1,0 porque el máximo de un cuadro de tasas —que incluye los
#: plazos largos y las activas de consumo— nunca cae bajo el 1,5% en ninguna plaza medida.
_UMBRAL_FRACCION = 1.5


def normalizar_escala(observaciones: List[Tuple[date, str, Optional[float]]],
                      ) -> Tuple[List[Tuple[date, str, Optional[float]]], List[str]]:
    """Lleva un cuadro de TASAS a porcentaje, y devuelve `(observaciones, avisos)`.

    **EMFA armoniza la metodología, no la ESCALA.** Medido sobre los siete archivos: las
    tasas de RD y Nicaragua vienen como fracción (0,58 = 58%) y las de Guatemala, Honduras,
    Costa Rica, Panamá y El Salvador ya vienen en porcentaje. Compararlas crudas pone un 0,58
    al lado de un 54,5 como si midieran lo mismo.

    Y cambia DENTRO de una misma serie: la tasa pasiva dominicana está en porcentaje hasta
    2003 (24,42) y en fracción desde 2004 (0,2457). Por eso la escala se decide por AÑO y no
    por cuadro — un único criterio para toda la serie dejaría cien veces mal a uno de los dos
    tramos.

    Lo que NO hace: adivinar por observación suelta. Un 0,6 aislado puede ser 0,6% o 60% y no
    hay forma de saberlo; la decisión se toma sobre el máximo del año, donde los plazos largos
    y el consumo fijan una cota que no deja lugar a duda.
    """
    por_anio: Dict[int, List[float]] = {}
    for corte, _, valor in observaciones:
        if valor is not None:
            por_anio.setdefault(corte.year, []).append(valor)

    escala = {anio: (100.0 if max(vs) <= _UMBRAL_FRACCION else 1.0)
              for anio, vs in por_anio.items() if vs}

    fuera: List[Tuple[date, str, Optional[float]]] = []
    avisos: List[str] = []
    for corte, etiqueta, valor in observaciones:
        if valor is None:
            fuera.append((corte, etiqueta, None))
            continue
        convertido = valor * escala.get(corte.year, 1.0)
        if convertido > TASA_MAXIMA_CREIBLE_PCT or convertido < 0:
            # Fail-closed: se descarta la observación y queda constancia. Publicar una tasa
            # de tres dígitos porque la normalización falló es peor que no publicarla.
            avisos.append(f"{corte} · {etiqueta[:40]}: {convertido:.2f}% fuera de rango")
            fuera.append((corte, etiqueta, None))
            continue
        fuera.append((corte, etiqueta, round(convertido, 4)))
    return fuera, avisos


def parse_cuadro(filas: List[List]) -> List[Tuple[date, str, Optional[float]]]:
    """``[(corte, etiqueta de columna, valor)]`` de un cuadro EMFA ya leído.

    Corta al terminar las observaciones: después de los datos vienen las notas al pie
    («1/ Incluye Microempresa»), que no son filas de datos.
    """
    par = _columnas_del_periodo(filas)
    if par is None:
        return []
    ca, cb = par

    cortes = _cortes_de_columna(filas, ca, cb)
    if not cortes:
        return []
    fila_datos = min(cortes)

    # El ancho es el de los DATOS, no el de la hoja. Las columnas de relleno a la derecha
    # no tienen encabezado propio y heredaban por propagación el rótulo de la última
    # columna real: dos columnas con la misma etiqueta, que es una clave que no identifica.
    ncols = 0
    for i in cortes:
        for j, celda in enumerate(filas[i]):
            if parse_valor(celda) is not None and j > cb:
                ncols = max(ncols, j + 1)
    etiquetas = etiquetas_de_columna(filas, fila_datos, ncols, primera_col=cb + 1)
    if not etiquetas:
        return []

    fuera: List[Tuple[date, str, Optional[float]]] = []
    maximo: Optional[date] = None
    for i, corte in sorted(cortes.items()):
        # Varias hojas APILAN un segundo cuadro debajo del primero, repitiendo las mismas
        # etiquetas y volviendo a empezar la serie en 2001. Leer los dos producía la misma
        # (corte, etiqueta) dos veces con valores distintos, y la base —que sí tiene la
        # restricción— lo rechaza. Un cuadro es una serie que avanza: cuando el corte
        # RETROCEDE, empezó otro bloque y este termina.
        if maximo is not None and corte < maximo:
            break
        if corte == maximo:
            # El corte se REPITE: en el cuadro de tasas de RD las filas de junio y julio de
            # 2024 dicen las dos «Jun» y la serie salta a agosto — una errata del emisor,
            # no del parser. No se puede saber cuál de las dos es julio, así que se
            # conserva la primera y se descarta la segunda: inventar la corrección sería
            # publicar un dato en un mes que nadie afirmó.
            logger.warning("[SECMCA] corte repetido %s en la fila %d: se conserva la "
                           "primera ocurrencia", corte, i)
            continue
        maximo = corte
        fila = filas[i]
        for col, etiqueta in etiquetas.items():
            if col < len(fila):
                fuera.append((corte, etiqueta, parse_valor(fila[col])))
    return fuera


def _cortes_de_columna(filas: List[List], ca: int, cb: int) -> Dict[int, date]:
    """``{índice de fila: corte}`` para un par de columnas, arrastrando el año."""
    fuera: Dict[int, date] = {}
    anio: Optional[int] = None
    mes_ancla: Optional[int] = None      # el mes de la fila donde se escribió ese año
    for i, fila in enumerate(filas):
        if len(fila) <= cb:
            continue
        texto_a = str(fila[ca] or "").strip()
        m = re.match(r"^(\d{2,4})(?:\.0)?$", texto_a)
        explicito = False
        if m:
            visto = int(m.group(1))
            if visto < 100:
                visto += 2000 if visto < 70 else 1900
            if 1990 <= visto <= date.today().year + 1:
                anio, mes_ancla, explicito = visto, None, True

        corte = parse_periodo(fila[ca], fila[cb], anio_arrastrado=anio)
        if corte is None:
            continue
        if explicito:
            mes_ancla = corte.month
        elif anio is None:
            # El corte salió de una celda con formato de fecha: trae su propio año y no
            # necesita arrastre. Se sincroniza el ancla para las filas que vengan después.
            anio, mes_ancla = corte.year, corte.month
        elif mes_ancla is not None and corte.month < mes_ancla:
            # El año se escribe en la fila de DICIEMBRE y los meses que siguen son del año
            # SIGUIENTE: «2001 Dic», «Ene»…«Nov», «2002 Dic». Arrastrar el año sin más
            # dejaba esos once meses un año atrás — la serie entera corrida, sin ningún
            # error visible. Cuando el mes retrocede respecto del ancla, cambió el año.
            anio += 1
            mes_ancla = corte.month
            corte = _fin_de_mes(anio, corte.month)
        else:
            mes_ancla = corte.month
        fuera[i] = corte
    return fuera


def _columnas_del_periodo(filas: List[List]) -> Optional[Tuple[int, int]]:
    """Qué par de columnas lleva el período. No se puede asumir ``(0, 1)``.

    Guatemala arranca con una columna vacía y pone el año en la 1 y el mes en la 2; Costa
    Rica trae la fecha en una sola columna. Se elige el par que reconoce MÁS observaciones,
    no el primero que reconoce alguna: en varios cuadros la columna del año trae también
    números sueltos que un par equivocado interpreta como un puñado de fechas válidas.
    """
    mejor, mejor_n = None, 0
    for ca in range(0, 3):
        for cb in range(ca, min(ca + 3, 4)):
            n = len(_cortes_de_columna(filas, ca, cb))
            if n > mejor_n:
                mejor, mejor_n = (ca, cb), n
    return mejor if mejor_n >= 2 else None


def filas_de_hoja(hoja, datemode: int) -> List[List]:
    """Las celdas de una hoja, con las de formato FECHA ya resueltas a `date`.

    La conversión se hace acá y no en el parseo porque el serial de Excel («42370») no se
    puede distinguir de un número cualquiera sin saber el tipo de la celda ni el `datemode`
    del libro. Resolverlo por rango de valores sería adivinar.
    """
    import xlrd

    fuera: List[List] = []
    for i in range(hoja.nrows):
        fila: List = []
        for j in range(hoja.ncols):
            valor = hoja.cell_value(i, j)
            if hoja.cell_type(i, j) == xlrd.XL_CELL_DATE:
                try:
                    a, m, d, *_ = xlrd.xldate_as_tuple(valor, datemode)
                    valor = date(a, m, d) if a else valor
                except (ValueError, xlrd.XLDateError):
                    pass
            fila.append(valor)
        fuera.append(fila)
    return fuera


def cuadros_del_libro(libro) -> Dict[str, List[Tuple[date, str, Optional[float]]]]:
    """``{clave de cuadro: observaciones}`` de un libro EMFA ya abierto.

    Cuando dos hojas resuelven al mismo cuadro se conserva la que trae MÁS observaciones
    con valor: El Salvador publica su tasa pasiva partida en dos hojas de título casi
    idéntico —una anual a diciembre y otra mensual—, y quedarse con la primera que aparece
    entregaría la más pobre según el orden del archivo, que no es un criterio.
    """
    fuera: Dict[str, List[Tuple[date, str, Optional[float]]]] = {}
    for nombre in libro.sheet_names():
        hoja = libro.sheet_by_name(nombre)
        if hoja.nrows < 10:
            continue
        filas = filas_de_hoja(hoja, libro.datemode)
        clave = clasificar_hoja(titulo_de_hoja(filas))
        if not clave:
            continue
        obs = parse_cuadro(filas)
        if clave.startswith("tasa_"):
            # Solo las tasas: los saldos de crédito van en moneda local y no tienen escala
            # que normalizar — de hecho el cuadro ni declara su unidad.
            obs, avisos = normalizar_escala(obs)
            for aviso in avisos[:5]:
                logger.warning("[SECMCA] tasa descartada por escala implausible: %s", aviso)
            if avisos:
                logger.warning("[SECMCA] %d observaciones descartadas en %s", len(avisos), clave)
        con_valor = sum(1 for o in obs if o[2] is not None)
        previas = fuera.get(clave)
        if previas is None or con_valor > sum(1 for o in previas if o[2] is not None):
            fuera[clave] = obs
    return fuera


# ── El conector ───────────────────────────────────────────────────────────────────────
LICENSE = ("SECMCA / CMCA — cuadros EMFA publicados para descarga en secmca.org. Sin "
           "términos de uso localizados: deuda de verificación declarada, no permiso "
           "presunto.")


class SecmcaError(RuntimeError):
    """La página o un cuadro de SECMCA no vinieron en la forma esperada."""


class SECMCAClient(FixtureBackedClient):
    """Cuadros EMFA del CMCA: crédito al sector privado y tasas bancarias, 7 plazas."""

    source = "SECMCA"
    license = LICENSE
    license_ok = True
    fixture_file = "secmca.json"
    live_phase = "boletín regional (T-BR-5)"

    #: Lo que EMFA armoniza es la METODOLOGÍA, no la unidad. Las tasas son porcentajes y
    #: se comparan entre países; el crédito viene en moneda local y el propio cuadro deja
    #: la unidad en blanco («Saldos en millones de ___»), así que solo admite trayectoria
    #: y variación dentro de cada país. Lo vigila el guard de T-BR-9.
    NORMA_CONTABLE = "EMFA armonizado"
    COMPARABLE_ENTRE_PAISES = {"tasa_activa_mn", "tasa_pasiva_mn"}

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return _filtrar(self._fetch_live(), series, period)
        return _filtrar(self._fetch_fixture(), series, period)

    # ── Live ──────────────────────────────────────────────────────
    def _fetch_live(self) -> List[Record]:  # pragma: no cover - network I/O
        import httpx
        import xlrd

        resp = httpx.get(EMFA_PAGE, timeout=60, follow_redirects=True,
                         headers={"User-Agent": "sdq-mip/1.0"})
        resp.raise_for_status()
        archivos = discover_country_files(resp.text)
        if not archivos:
            raise SecmcaError(
                f"ningún cuadro EMFA enlazado en {EMFA_PAGE}: cambió la página")

        fuera: List[Record] = []
        for iso3, url in sorted(archivos.items()):
            try:
                bruto = httpx.get(url, timeout=180, follow_redirects=True,
                                  headers={"User-Agent": "sdq-mip/1.0"})
                bruto.raise_for_status()
                libro = xlrd.open_workbook(file_contents=bruto.content)
            except Exception as e:  # noqa: BLE001 — un país que falla no tumba el resto
                logger.warning("[SECMCA] %s no se pudo leer: %s", iso3, e)
                continue
            fuera.extend(self._records_de(iso3, cuadros_del_libro(libro), url))
        return fuera

    def _records_de(self, iso3: str, cuadros: Dict, url: str) -> List[Record]:
        lineage = Lineage(source=self.source, license=self.license,
                          fetched_at=date.today(), url=url,
                          note="Cuadros EMFA del CMCA; corte declarado por país")
        fuera: List[Record] = []
        for clave, observaciones in cuadros.items():
            es_tasa = clave.startswith("tasa_")
            for corte, etiqueta, valor in observaciones:
                fuera.append(Record(
                    series=f"{clave}::{etiqueta}",
                    period=corte.isoformat(),
                    value=valor,
                    lineage=lineage,
                    # El cuadro de crédito NO declara su moneda («millones de ___»), así
                    # que la unidad se declara desconocida en vez de suponerla.
                    unit="%" if es_tasa else "moneda local, unidad no declarada",
                    dimension=iso3,
                    reason=None if valor is not None else "la fuente no publica el dato",
                ))
        return fuera

    # ── Fixture (offline) ─────────────────────────────────────────
    def _fetch_fixture(self) -> List[Record]:
        """Forma del fixture: ``{iso3: {"url": str, "cuadros": {clave: [[corte, col, v]]}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        fuera: List[Record] = []
        for iso3, bloque in fixture.items():
            if iso3.startswith("_"):
                continue
            cuadros = {
                clave: [(date.fromisoformat(c), col, v) for c, col, v in filas]
                for clave, filas in (bloque.get("cuadros") or {}).items()
            }
            fuera.extend(self._records_de(iso3, cuadros, bloque.get("url", "")))
        return fuera


def _filtrar(records: List[Record], series: Optional[str],
             period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


secmca_client = SECMCAClient()
