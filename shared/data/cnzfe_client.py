"""CNZFE connector — DR free-zone sector fundamentals (Eje Zonas Francas).

Public open data from the **Consejo Nacional de Zonas Francas de Exportación (CNZFE)**,
dataset "Evolución de las principales variables del Sector de Zonas Francas" on the
national open-data portal (datos.gob.do, CKAN). It is a clean yearly series (2006–) of
the sector's fundamentals — approved parks, operating companies, jobs, exports (US$),
accumulated investment (US$), local operating spend, weekly wages, occupied floor area —
the authoritative base for a free-zone attractiveness/health index.

CSV URLs change when CNZFE republishes, so we resolve the current CSV resource via the
CKAN ``package_show`` API, then fetch it. The file is UTF-8 (BOM) and comma-separated.

**Respaldo: el Informe Estadístico del propio CNZFE (2026-09-15).** Desde el 2026-09-14
datos.gob.do lista los recursos del CNZFE pero su descarga responde HTTP 500 —CSV, XLSX y ODS,
con la URL corta y con la completa—, mientras los recursos de otras organizaciones que apuntan
a su propio servidor (MIVHED) bajan bien: la falla es del almacén de archivos del portal. El
mismo cuadro ("Cuadro No. 1 — Evolución de las principales variables", 2006-2025, las nueve
columnas) viene en el PDF anual que el CNZFE publica en ``cnzfe.gob.do``. Si el CSV falla, se
lee de ahí y el resultado dice de dónde salió (``ultimo_origen``).

Dos detalles de ese camino, verificados: ``cnzfe.gob.do`` sirve una cadena TLS que termina en
«AAA Certificate Services», raíz que certifi ya no trae, así que la verificación falla aunque
el certificado es válido. NO se apaga la verificación: se agrega el intermedio oficial «SSL.com
TLS Transit ECC CA R2» emitido por «SSL.com TLS ECC Root CA 2022», que sí está en certifi
(``certs/ssl_com_tls_transit_ecc_ca_r2.crt``, bajado de su AIA; ``.crt`` y no ``.pem``
porque ``.gitignore`` excluye todo ``*.pem`` —con razón: suelen ser claves— y un certificado
público ignorado desaparece del deploy sin que ningún test local lo note). Y el texto de la página se
extrae con pypdfium2: pdfplumber no decodifica las fuentes de ese cuadro.
"""
import csv
import io
import logging
import pathlib
import re
from typing import Dict, Optional, Tuple

from shared.data.base_client import check_license_for

logger = logging.getLogger("sdq.data.cnzfe")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SLUG_VARS = "principales-variables-del-sector-de-zonas-francas-de-la-republica-dominicana-2006-2025"

# CSV header → canonical field. Matched accent/spacing-insensitively (see ``_norm``).
_FIELDS = {
    "total parques aprobados": "parks",
    "total empresas operando": "companies",
    "total de empleos": "jobs",
    "exportaciones millones us$": "exports_musd",
    "inversion total acumulada millones us$": "investment_musd",
    "gastos operativos locales millones us$": "local_spend_musd",
    "salarios operarios semanales rd$": "wage_operator_rd",
    "salarios tecnicos semanales rd$": "wage_technician_rd",
    "areas de naves ocupadas pies cuadrados": "occupied_area_sqft",
}


def _norm(s: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                if not unicodedata.combining(c))
    return " ".join(t.replace("(", " ").replace(")", " ").split())


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_free_zone_vars(text: str) -> Dict[int, Dict[str, float]]:
    """``{year: {field: value}}`` from the CNZFE evolution CSV.

    Maps the header columns to canonical fields; rows without a 4-digit year are
    skipped. Empty cells stay absent (never fabricated)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))  # tolera BOM
    header = next(reader, None)
    if not header:
        return {}
    # column index → canonical field (the year column is matched separately)
    cols: Dict[int, str] = {}
    year_col = None
    for i, h in enumerate(header):
        n = _norm(h)
        if n in ("ano", "año", "anio"):
            year_col = i
        elif n in _FIELDS:
            cols[i] = _FIELDS[n]
    if year_col is None:
        return {}
    out: Dict[int, Dict[str, float]] = {}
    for row in reader:
        if len(row) <= year_col:
            continue
        ys = row[year_col].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        rec: Dict[str, float] = {}
        for i, field in cols.items():
            if i < len(row):
                v = _num(row[i])
                if v is not None:
                    rec[field] = v
        if rec:
            out[int(ys)] = rec
    return out


class CNZFEClient:
    source = "CNZFE (Consejo Nacional de Zonas Francas)"
    # Verificado el 2026-08-23 contra el propio CKAN del portal
    # (`package_show` → `license_id: odc-odbl`) para el dataset que este conector consume,
    # no para el portal en general: el portal declara licencia POR DATASET y dar por buena
    # una sola cadena para todos era una suposición. Decía «Datos Abiertos RD
    # (datos.gob.do)», que no nombra ninguna cláusula — y ODbL tiene dos.
    license = ("datos.gob.do — Open Database License (ODbL) v1.0, declarada POR DATASET en el "
        "portal: exige el aviso de atribución, y el share-alike alcanza a las bases "
        "DERIVADAS. Un informe o un gráfico es «Produced Work» y NO lo dispara "
        "(§4.5) — https://opendatacommons.org/licenses/odbl/1-0/")
    license_ok = True

    def _resolve_csv(self, slug: str) -> str:
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            data = http.get(_CKAN, params={"id": slug}).json()
        for r in (data.get("result") or {}).get("resources", []):
            if (r.get("format") or "").upper() == "CSV" and r.get("url"):
                return r["url"]
        raise RuntimeError(f"CNZFE: sin recurso CSV para '{slug}'")

    #: De dónde salieron las variables en la última lectura: el CSV del portal o el informe.
    ultimo_origen: Optional[str] = None

    def _descargar(self, url: str) -> Tuple[int, str, bytes]:
        import httpx
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            r = http.get(url)
        return r.status_code, r.headers.get("content-type", ""), r.content

    def _fetch_csv(self, slug: str) -> str:
        url = self._resolve_csv(slug)
        status, tipo, contenido = self._descargar(url)
        # El portal responde su página de error en HTML: leída como CSV daba «no devolvió
        # variables», que ocultaba el HTTP 500.
        if status != 200 or "html" in tipo.lower():
            raise RuntimeError(f"CNZFE: el recurso CSV de '{slug}' respondió HTTP {status} ({url})")
        return contenido.decode("utf-8-sig")

    def free_zone_vars(self) -> Dict[int, Dict[str, float]]:
        try:
            variables = parse_free_zone_vars(self._fetch_csv(SLUG_VARS))
            if not variables:
                raise RuntimeError("CNZFE: el CSV de datos.gob.do no trajo filas legibles")
        except Exception as e:  # noqa: BLE001 — cualquier falla del portal cae al informe
            logger.warning("CNZFE: datos.gob.do no entregó el CSV (%s); se lee el Informe "
                           "Estadístico del CNZFE", e)
            variables = cnzfe_informe_client.free_zone_vars()
            self.ultimo_origen = (f"Informe Estadístico del CNZFE, Cuadro No. 1 (PDF, "
                                  f"cnzfe.gob.do); datos.gob.do falló: {e}")
            return variables
        self.ultimo_origen = "datos.gob.do (CSV del CNZFE)"
        return variables


_INFORMES = "https://cnzfe.gob.do/publicaciones/informes-estadisticos/"
_CA_CNZFE = pathlib.Path(__file__).parent / "certs" / "ssl_com_tls_transit_ecc_ca_r2.crt"
_RE_INFORME = re.compile(
    r"https://cnzfe\.gob\.do/wp-content/uploads/\d{4}/\d{2}/Informe-Estadistico-(\d{4})"
    r"[^\"'\s<>]*\.pdf", re.IGNORECASE)

#: Columnas del Cuadro No. 1, en su orden. El texto del PDF no conserva el encabezado en
#: orden, así que el orden se fija acá y las etiquetas se EXIGEN presentes: si el CNZFE agrega
#: o quita una columna, la lectura falla en vez de correr los valores de lugar.
_COLUMNAS_CUADRO_1 = ("parks", "companies", "jobs", "exports_musd", "investment_musd",
                      "local_spend_musd", "wage_operator_rd", "wage_technician_rd",
                      "occupied_area_sqft")
_ETIQUETAS_CUADRO_1 = ("parques", "empresas", "empleos", "exportaciones", "inversion total",
                       "gastos locales", "operarios", "tecnicos", "area de naves")
_NUMERO = re.compile(r"-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?")


def ultimo_informe(html: str) -> Tuple[int, str]:
    """``(año, url)`` del Informe Estadístico más reciente enlazado en la página de informes."""
    hallados: Dict[int, str] = {}
    for m in _RE_INFORME.finditer(html):
        hallados.setdefault(int(m.group(1)), m.group(0))
    if not hallados:
        raise RuntimeError("CNZFE: la página de informes estadísticos no enlaza ningún "
                           "Informe-Estadistico-AAAA.pdf")
    anio = max(hallados)
    return anio, hallados[anio]


def texto_del_cuadro_1(pdf: bytes) -> str:
    """El texto de la página del Cuadro No. 1 (principales variables), extraído con pypdfium2."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    try:
        for i in range(len(doc)):
            texto = doc[i].get_textpage().get_text_range()
            n = _norm(texto)
            if re.search(r"cuadro no\.? ?1\b", n) and "principales variables" in n:
                return texto
    finally:
        doc.close()
    raise RuntimeError("CNZFE: el informe no trae el Cuadro No. 1 de principales variables")


def parse_cuadro_1(texto: str) -> Dict[int, Dict[str, float]]:
    """``{año: {campo: valor}}`` del Cuadro No. 1. Falla cerrado ante cualquier cambio de forma."""
    # Las etiquetas se buscan fuera de la nota de fuente: «Fuente de exportaciones y gastos
    # locales» las nombra y daba por presente una columna que ya no estaba.
    n = _norm(" ".join(linea for linea in texto.splitlines()
                       if not _norm(linea).startswith("fuente")))
    faltan = [e for e in _ETIQUETAS_CUADRO_1 if e not in n]
    if faltan:
        raise RuntimeError(f"CNZFE: el Cuadro No. 1 cambió de estructura; faltan las columnas "
                           f"{faltan}")
    out: Dict[int, Dict[str, float]] = {}
    for linea in texto.splitlines():
        partes = linea.split()
        if not partes or not re.fullmatch(r"(19|20)\d{2}", partes[0]):
            continue
        valores = partes[1:]
        if (len(valores) != len(_COLUMNAS_CUADRO_1)
                or not all(_NUMERO.fullmatch(v) for v in valores)):
            raise RuntimeError(f"CNZFE: fila del Cuadro No. 1 con {len(valores)} valores en vez de "
                               f"{len(_COLUMNAS_CUADRO_1)}: {linea.strip()!r}")
        out[int(partes[0])] = {c: float(v.replace(",", ""))
                               for c, v in zip(_COLUMNAS_CUADRO_1, valores)}
    if len(out) < 5:
        raise RuntimeError(f"CNZFE: el Cuadro No. 1 trajo {len(out)} años legibles")
    return out


class CNZFEInformeClient:
    """El Informe Estadístico anual del CNZFE en su propio sitio: respaldo del CSV del portal."""

    source = "CNZFE — Informe Estadístico (cnzfe.gob.do)"
    license = ("CNZFE — Informe Estadístico publicado en cnzfe.gob.do; es el mismo cuadro que el "
               "CNZFE publica bajo ODbL en datos.gob.do. Emisor público dominicano: reutilizable "
               "con atribución (Ley 200-04, Decreto 103-22).")
    license_ok = True

    def _ssl(self):
        import ssl

        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.load_verify_locations(cafile=str(_CA_CNZFE))
        return ctx

    def _get(self, url: str) -> bytes:
        import httpx
        with httpx.Client(timeout=180, follow_redirects=True, headers=_HEADERS,
                          verify=self._ssl()) as http:
            r = http.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"CNZFE: {url} respondió HTTP {r.status_code}")
        return r.content

    def free_zone_vars(self) -> Dict[int, Dict[str, float]]:
        check_license_for(self.source, self.license, self.license_ok)
        _, url = ultimo_informe(self._get(_INFORMES).decode("utf-8", "replace"))
        return parse_cuadro_1(texto_del_cuadro_1(self._get(url)))


cnzfe_informe_client = CNZFEInformeClient()
cnzfe_client = CNZFEClient()
