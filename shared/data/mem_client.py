"""MEM — los tres índices comerciales del sector eléctrico, del anexo del Informe de Desempeño.

El Ministerio de Energía y Minas publica cada mes un **anexo XLSX** junto a su Informe de
Desempeño de las Empresas Eléctricas Estatales. Su hoja ``EDE's`` trae, agregado para las tres
distribuidoras, exactamente las tres magnitudes que la Ley 1-12 fija como indicadores 3.27,
3.28 y 3.29 — y el CRI viene con el mismo nombre que usa el legislador, «Índice de
Recuperación de Efectivo».

**Solo se leen los anexos de DICIEMBRE, y no es una comodidad.** Las columnas del anexo son
ventanas ACUMULADAS del año en curso: la de abril dice `Ene24-Abr24`. Tomar esa cifra como el
año sería publicar cuatro meses con el rótulo de doce, y en un indicador estacional eso no es
una aproximación, es otro número. La de diciembre dice `Ene24-Dic24` y es el año completo.
Cada anexo de diciembre trae además los DOS años anteriores, así que dos archivos cubren seis
años.

**Nada se lee por posición.** El año sale de la cabecera y la fila sale de su ETIQUETA. Un
anexo cambia de una edición a otra —entre 2021 y 2024 se agregaron hojas y el bloque
financiero se corrió una fila— y un parser por índice habría seguido devolviendo el número de
al lado sin fallar. Si una etiqueta no aparece, esto levanta excepción en vez de servir un
diccionario incompleto.

**Lo que este módulo NO sirve: el subsidio del Estado (indicador 3.30).** Está en el anexo,
en la hoja de resultados financieros, y ahí la disciplina se rompe: esa hoja no tiene cabecera
de años y su fila se mueve entre ediciones (f63 en 2021, f64 en 2024). Leerla por posición
sería fabricar procedencia. Se declara como brecha y no se adivina.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

import httpx

logger = logging.getLogger("sdq.data.mem")

SOURCE = "MEM · Informe de Desempeño (anexo)"
BASE_CATEGORIA = "https://mem.gob.do/category/sector-electrico/informe-de-desempeno"
HOJA = "EDE's"
_TIMEOUT = 120
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"

#: Etiqueta en el anexo → clave de serie. Se toma la variante **Año Móvil** porque es la que
#: el emisor calcula sobre doce meses; en el anexo de diciembre coincide con la acumulada, y
#: preferirla deja el parser correcto si algún día se leyera otro mes.
FILAS = {
    "CRI - Año Movil (%)": "cri",
    "Pérdidas - Año Movil (%)": "perdidas",
    "Cobranzas - Año Movil (%)": "cobranzas",
}

#: `Ene24-Dic24`. Los dos años tienen que coincidir: una ventana `Ene24-Abr24` no es un año y
#: no entra. Es el guard que separa «doce meses» de «lo que va del año».
_RX_ANIO = re.compile(r"^\s*Ene(\d{2})\s*-\s*Dic(\d{2})\s*$", re.I)

_RX_XLSX_DIC = re.compile(r'href="([^"]*[Dd]iciembre[^"]*\.xlsx)"')


class MEMUnavailable(RuntimeError):
    """No se pudo obtener o leer el anexo. NUNCA se degrada a «no hay dato»."""


def anexos_de_diciembre(anios: List[int]) -> Dict[int, str]:
    """URL del anexo de diciembre por año de informe, descubierta del sitio del emisor.

    Se descubre en vez de fijarse: la ruta del archivo lleva el año y el mes en que se SUBIÓ,
    no el que mide (el de diciembre de 2024 vive bajo `/2025/03/`), así que componerla a mano
    la erraría cada vez que el emisor publica tarde.
    """
    out: Dict[int, str] = {}
    for a in anios:
        url = f"{BASE_CATEGORIA}/{a}-informe-de-desempeno/"
        try:
            r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": _UA})
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("MEM: no se pudo listar el año %s (%s)", a, e)
            continue
        halladas = _RX_XLSX_DIC.findall(r.text)
        if halladas:
            out[a] = halladas[0]
    return out


def _columnas_de_anio(ws) -> Dict[int, int]:
    """Columna → año, leído de la cabecera. Solo entran las ventanas de DOCE meses."""
    cols: Dict[int, int] = {}
    for fila in (5, 6, 7):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(fila, c).value
            if not isinstance(v, str):
                continue
            m = _RX_ANIO.match(v)
            if m and m.group(1) == m.group(2):
                cols[c] = 2000 + int(m.group(1))
    return cols


def parse_anexo(contenido: bytes) -> Dict[str, Dict[int, float]]:
    """`{serie: {año: porcentaje}}` del anexo de un diciembre.

    El emisor guarda estas celdas como fracción y las MUESTRA como porcentaje. Se publica el
    porcentaje —que es lo que se lee en su informe y la magnitud en que la ley escribió sus
    metas— y no se convierte nada más: cualquier otro ajuste dejaría de cuadrar contra la
    fuente el día que alguien coteje.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(_io(contenido), data_only=True, read_only=True)
    except Exception as e:                                   # archivo corrupto o no-xlsx
        raise MEMUnavailable(f"no se pudo abrir el anexo ({type(e).__name__}: {e})")
    if HOJA not in wb.sheetnames:
        raise MEMUnavailable(f"el anexo no trae la hoja «{HOJA}»; hojas: {wb.sheetnames}")
    ws = wb[HOJA]

    cols = _columnas_de_anio(ws)
    if not cols:
        raise MEMUnavailable(
            "ninguna columna del anexo declara un año completo `EneNN-DicNN`. Puede ser un "
            "anexo de otro mes: sus columnas son acumuladas y no son el año.")

    etiquetas = {e: None for e in FILAS}
    for fila in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=3):
        for celda in fila:
            v = celda.value
            if isinstance(v, str) and (t := " ".join(v.split())) in etiquetas:
                etiquetas[t] = celda.row

    if (faltan := [e for e, r in etiquetas.items() if r is None]):
        raise MEMUnavailable(
            f"el anexo no trae las filas {faltan}. Se busca por etiqueta a propósito: leerlas "
            f"por posición devolvería el número de al lado sin fallar.")

    out: Dict[str, Dict[int, float]] = {}
    for etiqueta, clave in FILAS.items():
        fila = etiquetas[etiqueta]
        serie: Dict[int, float] = {}
        for c, anio in sorted(cols.items()):
            v = ws.cell(fila, c).value
            if isinstance(v, (int, float)):
                serie[anio] = round(float(v) * 100.0, 4)
        out[clave] = serie
    return out


def _io(contenido: bytes):
    import io

    return io.BytesIO(contenido)


def descargar(url: str) -> bytes:  # pragma: no cover - I/O de red
    try:
        r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": _UA})
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise MEMUnavailable(f"no se pudo descargar el anexo ({type(e).__name__}: {e})")


def series_anuales(anios: List[int], listar=None, bajar=None,
                   ) -> Dict[str, List[Tuple[str, float]]]:
    """`{serie: [(año, valor)]}` ascendente, uniendo los anexos de diciembre disponibles.

    Cada anexo trae tres años y los años se solapan entre archivos. Manda el archivo MÁS
    NUEVO: el emisor revisa sus cifras y la edición reciente es la que él sostiene hoy. La
    discrepancia se registra en vez de resolverse en silencio — un dato que cambia de valor
    entre ediciones es exactamente lo que un lector puede reprocharle a un informe viejo.

    `listar` y `bajar` se inyectan para que los tests ejerciten esta lógica sin red: la regla
    de precedencia entre ediciones es justo lo que hay que poder probar, y contra el sitio
    del emisor no se prueba nada.
    """
    listar = listar or anexos_de_diciembre
    bajar = bajar or descargar
    urls = listar(sorted(anios))
    if not urls:
        raise MEMUnavailable("el emisor no publicó ningún anexo de diciembre alcanzable")
    acumulado: Dict[str, Dict[int, float]] = {c: {} for c in FILAS.values()}
    for anio_informe in sorted(urls):                 # del más viejo al más nuevo
        datos = parse_anexo(bajar(urls[anio_informe]))
        for clave, serie in datos.items():
            for a, v in serie.items():
                previo = acumulado[clave].get(a)
                if previo is not None and abs(previo - v) > 0.05:
                    logger.info("MEM: %s %s revisado por el emisor: %.2f → %.2f",
                                clave, a, previo, v)
                acumulado[clave][a] = v
    return {c: [(str(a), v) for a, v in sorted(s.items())] for c, s in acumulado.items()}
