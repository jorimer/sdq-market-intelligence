"""MIVHED connector — DR building-permit activity (Eje Construcción).

Public open data from the **Ministerio de la Vivienda, Hábitat y Edificaciones
(MIVHED)**, dataset "Licencias emitidas por MIVHED" on the national open-data portal
(datos.gob.do, CKAN). It is a TRANSACTIONAL file — one row per construction permit — with
issue date, province, municipality, typology, square metres and total investment (RD$).
Permitting is the canonical *leading* indicator of construction activity: it precedes the
actual build, so it anchors the pipeline dimension of the construction index (ICC).

The CSV opens with two banner rows before the real header ("Fecha de Emisión, Mes, Año,
…"); we locate the header row tolerantly. CSV URLs change when MIVHED republishes, so we
resolve the current CSV resource via the CKAN ``package_show`` API, then fetch it. The
file is UTF-8 (BOM) and comma-separated; the issue date is ``MM/DD/YYYY``.

We aggregate to ANNUAL totals (permits, m², investment) plus the per-typology and
per-province permit mix (for the diversification dimensions). The number of distinct
months present per year is kept so the caller can drop a partial current year — never
fabricating a full year from a quarter.
"""
import csv
import io
import logging
import unicodedata
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("sdq.data.mivhed")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SLUG_LICENSES = "licencias-emitidas"

# Canonical header tokens (normalized) → field role.
_COL_YEAR = ("ano",)            # "Año"
_COL_MONTH = ("mes",)
_COL_TYPOLOGY = ("tipologia",)
_COL_SQM = ("metros cuadrados",)
_COL_INVESTMENT = ("inversion total",)
_COL_PROVINCE = ("provincia",)
_COL_MUNICIPIO = ("municipio",)
_COL_BARRIO = ("barrio/sector", "barrio sector", "barrio")


def _norm(s: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", str(s).lower())
                if not unicodedata.combining(c))
    return " ".join(t.replace("(", " ").replace(")", " ").split())


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _find_header(rows) -> Optional[int]:
    """Index of the row that carries the real column header (the one with a year column
    AND a typology/sqm column) — skips the banner rows."""
    for i, row in enumerate(rows[:10]):
        norms = {_norm(c) for c in row}
        if any(t in norms for t in _COL_YEAR) and (
                any(t in norms for t in _COL_TYPOLOGY)
                or any(t in norms for t in _COL_SQM)):
            return i
    return None


def parse_licenses(text: str) -> Dict[int, Dict[str, Any]]:
    """``{year: {permits, sqm, investment, months, by_typology, by_typology_detail,
    by_province}}`` from the MIVHED permit CSV.

    Aggregates the per-permit rows to annual totals. ``months`` is the count of distinct
    months seen that year (so the caller can drop a partial year). Empty numeric cells are
    treated as 0 for the totals but never fabricated as a year.

    ``by_typology`` is the per-typology PERMIT COUNT (drives the HHI diversification
    dimension). ``by_typology_detail`` desagrega además los m² licenciados y la ``inversion``
    por tipología — ``{typology: {permits, sqm, investment}}`` — porque esos campos ya vienen
    en el dataset crudo por fila; sostiene la lectura de m² licenciados por tipo de
    construcción (p.ej. Comercial y oficinas).

    ⚠️ AVISO sobre ``investment`` (columna "Inversión Total" del MIVHED): NO es un valor
    declarado ni tasado por permiso — es un **costo estándar derivado** = m² × una tarifa fija
    por año (verificado 2026-07-14: el 94 % de las filas es exactamente m² × RD$61,600 y el
    resto m² × RD$57,200). Por tipología es por tanto **redundante con los m²** (comparte la
    misma tarifa) y NO equivale al "valor tasado" de la ONE (≈RD$14,946/m² tasado, ~4× menor).
    Se conserva por fidelidad al dato crudo, pero el producto NO lo expone por tipología como
    métrica monetaria independiente — la señal real por tipología son los m²."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    hi = _find_header(rows)
    if hi is None:
        return {}
    header = rows[hi]
    idx: Dict[str, int] = {}
    for i, h in enumerate(header):
        n = _norm(h)
        if n in _COL_YEAR:
            idx["year"] = i
        elif n in _COL_MONTH:
            idx["month"] = i
        elif n in _COL_TYPOLOGY:
            idx["typology"] = i
        elif n in _COL_SQM:
            idx["sqm"] = i
        elif n in _COL_INVESTMENT:
            idx["investment"] = i
        elif n in _COL_PROVINCE:
            idx["province"] = i
    if "year" not in idx:
        return {}

    out: Dict[int, Dict[str, Any]] = {}
    for row in rows[hi + 1:]:
        if len(row) <= idx["year"]:
            continue
        ys = row[idx["year"]].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        year = int(ys)
        rec = out.setdefault(year, {"permits": 0, "sqm": 0.0, "investment": 0.0,
                                    "_months": set(), "by_typology": {},
                                    "by_typology_detail": {}, "by_province": {}})
        rec["permits"] += 1
        sqm = _num(row[idx["sqm"]]) if "sqm" in idx and idx["sqm"] < len(row) else None
        inv = (_num(row[idx["investment"]])
               if "investment" in idx and idx["investment"] < len(row) else None)
        sqm_val, inv_val = sqm or 0.0, inv or 0.0
        rec["sqm"] += sqm_val
        rec["investment"] += inv_val
        if "month" in idx and idx["month"] < len(row):
            m = row[idx["month"]].strip().upper()
            if m:
                rec["_months"].add(m)
        if "typology" in idx and idx["typology"] < len(row):
            t = row[idx["typology"]].strip().upper() or "SIN CLASIFICAR"
            rec["by_typology"][t] = rec["by_typology"].get(t, 0) + 1
            d = rec["by_typology_detail"].setdefault(
                t, {"permits": 0, "sqm": 0.0, "investment": 0.0})
            d["permits"] += 1
            d["sqm"] += sqm_val
            d["investment"] += inv_val
        if "province" in idx and idx["province"] < len(row):
            p = row[idx["province"]].strip().upper() or "SIN PROVINCIA"
            rec["by_province"][p] = rec["by_province"].get(p, 0) + 1

    for rec in out.values():
        rec["months"] = len(rec.pop("_months"))
    return out


#: Nombre del mes tal como lo escribe el MIVHED (mayúsculas, español) → número.
#: Se lee la columna `Mes`, que el emisor DECLARA, en vez de derivarla de `Fecha de Emisión`:
#: son dos declaraciones del mismo hecho y la del emisor manda. Un nombre que no esté acá no
#: se adivina — la fila queda fuera del mes, declarada, nunca repartida.
_MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
          "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11,
          "DICIEMBRE": 12}


def parse_licenses_mensual(text: str) -> Dict[str, Any]:
    """``{"periodos": {"AAAA-MM": {...}}, "sin_mes": N}`` del CSV de permisos del MIVHED.

    **Por qué existe al lado de :func:`parse_licenses` y no dentro.** El CSV trae UNA FILA POR
    PERMISO con su año y su mes declarados por el emisor; la agregación anual es NUESTRA, no
    la forma del dato. Durante años se leyó el mes solo para contarlo (``months``, para
    descartar años parciales) y se tiraba. Acá se conserva.

    ``parse_licenses`` NO se toca: el ICC anual se calcula sobre ella y no puede moverse por
    este cambio. Dos lectores del mismo fichero es deliberado — el precio de no arriesgar el
    índice publicado.

    **Un flujo mensual REAL, no un acumulado parcial.** Cada valor es lo emitido EN ese mes.
    Es lo que hace comparable un mes contra el mismo mes del año anterior; sumar meses de un
    acumulado del ejercicio habría producido un dato falso, no un dato parcial.

    **Una fila sin mes legible no se reparte ni se asigna al año.** Queda fuera y se cuenta en
    ``sin_mes``, para que la brecha se pueda leer en vez de tener que sospecharla: un total que
    absorbe en silencio lo que no supo clasificar miente.

    El descarte va en una clave HERMANA de ``periodos`` y no dentro del mismo mapa: una clave
    que no es un período conviviendo con los períodos es una trampa para el primero que itere
    el diccionario, y ese defecto no falla — produce un mes fantasma.

    ⚠️ ``investment`` arrastra el mismo aviso que la anual: es un costo estándar derivado
    (m² × tarifa fija del año), NO un valor tasado ni declarado por permiso. Es redundante
    con los m² y no debe publicarse como magnitud monetaria independiente.
    """
    vacio: Dict[str, Any] = {"periodos": {}, "sin_mes": 0}
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    hi = _find_header(rows)
    if hi is None:
        return vacio
    header = rows[hi]
    idx: Dict[str, int] = {}
    for i, h in enumerate(header):
        n = _norm(h)
        if n in _COL_YEAR:
            idx["year"] = i
        elif n in _COL_MONTH:
            idx["month"] = i
        elif n in _COL_TYPOLOGY:
            idx["typology"] = i
        elif n in _COL_SQM:
            idx["sqm"] = i
        elif n in _COL_INVESTMENT:
            idx["investment"] = i
        elif n in _COL_PROVINCE:
            idx["province"] = i
        elif n in _COL_MUNICIPIO:
            idx["municipio"] = i
        elif n in _COL_BARRIO:
            idx["barrio"] = i
    if "year" not in idx or "month" not in idx:
        # Sin columna de mes no hay serie mensual que construir. Devolver el anual
        # re-etiquetado sería inventar doce puntos donde el emisor declaró uno.
        return vacio

    out: Dict[str, Dict[str, Any]] = {}
    sin_mes = 0
    for row in rows[hi + 1:]:
        if len(row) <= idx["year"] or len(row) <= idx["month"]:
            continue
        ys = row[idx["year"]].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        mes = _MESES.get(row[idx["month"]].strip().upper())
        if mes is None:
            sin_mes += 1
            continue
        periodo = f"{int(ys):04d}-{mes:02d}"
        rec = out.setdefault(periodo, {"permits": 0, "sqm": 0.0, "investment": 0.0,
                                       "by_typology": {}, "by_province": {},
                                       "by_municipio": {}, "by_barrio": {}})
        rec["permits"] += 1
        sqm = _num(row[idx["sqm"]]) if "sqm" in idx and idx["sqm"] < len(row) else None
        inv = (_num(row[idx["investment"]])
               if "investment" in idx and idx["investment"] < len(row) else None)
        sqm_val, inv_val = sqm or 0.0, inv or 0.0
        rec["sqm"] += sqm_val
        rec["investment"] += inv_val
        if "typology" in idx and idx["typology"] < len(row):
            t = row[idx["typology"]].strip().upper() or "SIN CLASIFICAR"
            d = rec["by_typology"].setdefault(t, {"permits": 0, "sqm": 0.0})
            d["permits"] += 1
            d["sqm"] += sqm_val
        if "province" in idx and idx["province"] < len(row):
            p = row[idx["province"]].strip().upper() or "SIN PROVINCIA"
            d = rec["by_province"].setdefault(p, {"permits": 0, "sqm": 0.0})
            d["permits"] += 1
            d["sqm"] += sqm_val
            # MUNICIPIO y BARRIO viajan con los niveles de arriba en la llave: hay barrios con el
            # mismo nombre en municipios distintos («CENTRO», «LOS JARDINES») y municipios con
            # nombres que se repiten en otra provincia. Sumar por nombre suelto fundiría plazas
            # que el emisor separa.
            if "municipio" in idx and idx["municipio"] < len(row):
                m = row[idx["municipio"]].strip().upper() or "SIN MUNICIPIO"
                dm = rec["by_municipio"].setdefault((p, m), {"permits": 0, "sqm": 0.0})
                dm["permits"] += 1
                dm["sqm"] += sqm_val
                if "barrio" in idx and idx["barrio"] < len(row):
                    b = row[idx["barrio"]].strip().upper() or "SIN BARRIO"
                    db_ = rec["by_barrio"].setdefault((p, m, b), {"permits": 0, "sqm": 0.0})
                    db_["permits"] += 1
                    db_["sqm"] += sqm_val

    return {"periodos": out, "sin_mes": sin_mes}


class MIVHEDClient:
    source = "MIVHED (Ministerio de la Vivienda, Hábitat y Edificaciones)"
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

    def _resolve_recurso(self, slug: str) -> Tuple[str, Optional[str]]:
        """``(url del CSV, fecha en que el emisor lo publicó por última vez)``.

        La fecha sale del CKAN del portal: es la única evidencia de CUÁNDO publicó el emisor, y
        el dato no la trae. Se descartaba al resolver la URL. Sin ella, «la fuente no publica
        desde tal fecha» solo se podría escribir a mano — y una fecha transcrita es una fecha
        que se desincroniza con la primera edición nueva.

        **En la práctica sale de ``metadata_modified``, no de ``last_modified``.** Verificado el
        2026-09-10 sobre los cuatro recursos del dataset (CSV, XLSX, ODS, JSON): el portal deja
        ``last_modified`` en ``None`` y registra la subida en ``metadata_modified``. Se prefiere
        ``last_modified`` si algún día viene, porque es el campo que nombra la subida del
        fichero; ``metadata_modified`` también se mueve si alguien edita solo la descripción del
        recurso, así que es un respaldo, no un sinónimo. Para el MIVHED coincide con la carpeta
        de subida de la URL (``/uploads/2026/07/`` para la edición del 21 de julio), que es lo
        que lo sostiene como fecha de publicación.

        ``None`` si el portal no declara ninguna de las dos: se dice que no se sabe, no se
        inventa.
        """
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            data = http.get(_CKAN, params={"id": slug}).json()
        for r in (data.get("result") or {}).get("resources", []):
            if (r.get("format") or "").upper() == "CSV" and r.get("url"):
                crudo = str(r.get("last_modified") or r.get("metadata_modified") or "")
                return r["url"], (crudo[:10] if len(crudo) >= 10 else None)
        raise RuntimeError(f"MIVHED: sin recurso CSV para '{slug}'")

    def _resolve_csv(self, slug: str) -> str:
        return self._resolve_recurso(slug)[0]

    def _fetch_csv_con_fecha(self, slug: str) -> Tuple[str, Optional[str]]:
        """El CSV y la fecha de su última publicación, de UNA sola resolución del recurso."""
        import httpx
        url, publicado_el = self._resolve_recurso(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("utf-8-sig"), publicado_el

    def _fetch_csv(self, slug: str) -> str:
        return self._fetch_csv_con_fecha(slug)[0]

    def licenses(self) -> Dict[int, Dict[str, Any]]:
        return parse_licenses(self._fetch_csv(SLUG_LICENSES))

    def licenses_mensual(self) -> Dict[str, Any]:
        """La misma descarga, leída por MES, con la fecha de publicación del emisor."""
        text, publicado_el = self._fetch_csv_con_fecha(SLUG_LICENSES)
        return {**parse_licenses_mensual(text), "publicado_el": publicado_el}

    def licenses_ambas(self) -> Dict[str, Any]:
        """Anual y mensual de UNA sola descarga.

        El CSV son decenas de miles de filas y el sync ya lo baja para el ICC. Pedirlo dos
        veces sería pagar la red dos veces por el mismo fichero — y, peor, admitir que las
        dos lecturas correspondan a descargas distintas: si el emisor publica entre una y
        otra, el mensual y el anual del mismo informe dejarían de cuadrar.
        """
        text, publicado_el = self._fetch_csv_con_fecha(SLUG_LICENSES)
        return {"anual": parse_licenses(text),
                "mensual": {**parse_licenses_mensual(text), "publicado_el": publicado_el}}


mivhed_client = MIVHEDClient()
