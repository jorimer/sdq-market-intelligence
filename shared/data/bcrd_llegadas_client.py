"""BCRD — llegada mensual de pasajeros no residentes vía aérea (Eje Turismo, feed mensual).

El Banco Central publica ``lleg_total.xls`` en su CDN público (sin token ni allowlist, a
diferencia de la API de MacroVariables). La hoja «No Residentes 78 - 26» apila un bloque por
año —la fila del año («1978», «2026*» con asterisco si es preliminar) y debajo los doce
meses— con tres grupos de columnas: **Total** de no residentes, **Dominicanos** no residentes
(la diáspora) y **Extranjeros** no residentes. Cada grupo trae el valor mensual y la tasa de
crecimiento «Igual Mes» del año anterior.

**Por qué un lector propio y no `mm_series`.** El motor de planillas persiste este archivo en
98 series fragmentadas por hoja y corte, y el registro canónico lo marca sin UNA serie que
citar (`llegada_turistas`, `flagged`). El feed necesita tres series limpias, y un módulo no lee
la tabla de otro. Se lee la hoja una vez, acá, y se escribe a `sector_observations`.

**La columna se VERIFICA, no se supone.** Para cada grupo, el crecimiento que calculamos contra
el mismo mes del año anterior tiene que coincidir con la «Tasa de Crecimiento Igual Mes» que
publica el propio BCRD en la misma fila. Si una columna se corriera —un grupo nuevo, un
reordenamiento—, el cociente dejaría de cerrar y el parseo falla en vez de publicar la
diáspora como si fueran los extranjeros. Verificado el 2026-09-14: julio de 2026 contra julio
de 2025 da 6,70338 % y el BCRD publica 6,70338 %.

Las cifras no son enteras (820.079,70 personas): el BCRD publica estimaciones expandidas. Se
guardan como vienen; redondearlas sería cambiar el dato del emisor.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.data.base_client import _FIXTURES_DIR, Mode, Record, SourceClient
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.bcrd_llegadas")

URL_LLEGADAS = ("https://cdn.bancentral.gov.do/documents/estadisticas/sector-turismo/"
                "documents/lleg_total.xls")
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}
HOJA_NO_RESIDENTES = "No Residentes 78 - 26"
_PREFIJO_HOJA = "no residentes"

SERIE_TOTAL = "bcrd.llegadas.no_residentes.total"
SERIE_DOMINICANOS = "bcrd.llegadas.no_residentes.dominicanos"
SERIE_EXTRANJEROS = "bcrd.llegadas.no_residentes.extranjeros"

#: Rótulo del grupo en la fila de cabecera → serie. La columna se LOCALIZA por el rótulo, no por
#: su posición, y después se verifica contra la tasa publicada.
GRUPOS: Dict[str, str] = {
    "total": SERIE_TOTAL,
    "dominicanos": SERIE_DOMINICANOS,
    "extranjeros": SERIE_EXTRANJEROS,
}
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
          "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
_RE_ANIO = re.compile(r"^\s*(\d{4})(?:\.0)?\s*\*?\s*$")
#: Puntos porcentuales de tolerancia entre la tasa calculada y la publicada (redondeo del emisor).
_TOLERANCIA_PP = 0.01


class EstructuraInesperada(ValueError):
    """La hoja no tiene la forma verificada. Se falla: adivinar publicaría cifras corridas."""


@dataclass(frozen=True)
class EdicionLlegadas:
    periodo: str                 # el último mes con dato, "YYYY-MM"
    publicada: Optional[date]    # Last-Modified del CDN: cuándo subió el BCRD el archivo


def _norm(v: Any) -> str:
    import unicodedata

    t = "".join(c for c in unicodedata.normalize("NFKD", str(v).lower())
                if not unicodedata.combining(c))
    return " ".join(t.split())


def _numero(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None   # «-», «n.d.» o un texto no son cifras


def _columnas(filas: Sequence[Sequence[Any]]) -> Tuple[int, Dict[str, Tuple[int, int]]]:
    """``(fila donde empieza el dato, {serie: (col mensual, col igual mes)})``."""
    for i, fila in enumerate(filas[:20]):
        rotulos = {_norm(v): j for j, v in enumerate(fila) if str(v).strip()}
        if all(g in rotulos for g in GRUPOS):
            sub = filas[i + 1] if i + 1 < len(filas) else []
            cols: Dict[str, Tuple[int, int]] = {}
            for grupo, serie in GRUPOS.items():
                inicio = rotulos[grupo]
                mensual = next((j for j in range(inicio, min(inicio + 3, len(sub)))
                                if _norm(sub[j]) == "mensual"), None)
                igual = next((j for j in range(inicio, min(inicio + 6, len(sub)))
                              if _norm(sub[j]).startswith("igual mes")), None)
                if mensual is None or igual is None:
                    raise EstructuraInesperada(
                        f"BCRD llegadas: el grupo «{grupo}» no trae «Mensual» e «Igual Mes».")
                cols[serie] = (mensual, igual)
            return i + 2, cols
    raise EstructuraInesperada("BCRD llegadas: no se encontró la cabecera Total / Dominicanos / "
                               "Extranjeros en la hoja de no residentes.")


def parse_hoja_no_residentes(filas: Sequence[Sequence[Any]]) -> Dict[str, Dict[str, Optional[float]]]:
    """``{serie: {"YYYY-MM": personas}}`` de la hoja, con cada grupo verificado."""
    inicio, cols = _columnas(filas)
    series: Dict[str, Dict[str, Optional[float]]] = {s: {} for s in cols}
    publicadas: Dict[str, Dict[str, Optional[float]]] = {s: {} for s in cols}
    anio: Optional[int] = None
    for fila in filas[inicio:]:
        if not fila:
            continue
        rotulo = str(fila[0]).strip()
        m = _RE_ANIO.match(rotulo)
        if m:
            anio = int(m.group(1))
            continue
        mes = _MESES.get(_norm(rotulo))
        if mes is None or anio is None:
            continue
        periodo = f"{anio}-{mes:02d}"
        for serie, (c_mensual, c_igual) in cols.items():
            valor = _numero(fila[c_mensual]) if c_mensual < len(fila) else None
            if valor is None:
                continue          # el mes todavía no publicado viene vacío: no se lee
            series[serie][periodo] = valor
            publicadas[serie][periodo] = _numero(fila[c_igual]) if c_igual < len(fila) else None
    if not series[SERIE_TOTAL]:
        raise EstructuraInesperada("BCRD llegadas: la hoja no trae ningún mes con dato.")

    # LA COLUMNA SE VERIFICA contra la tasa que publica el BCRD, en el último mes con base.
    for serie, puntos in series.items():
        ultimo = max(puntos)
        anio_u, mes_u = (int(x) for x in ultimo.split("-"))
        base = puntos.get(f"{anio_u - 1}-{mes_u:02d}")
        actual = puntos.get(ultimo)
        tasa = publicadas[serie].get(ultimo)
        if not base or actual is None or tasa is None:
            raise EstructuraInesperada(f"BCRD llegadas: {serie} en {ultimo} no tiene base o tasa "
                                       f"publicada para verificar la columna.")
        calculada = (actual / base - 1) * 100
        if abs(calculada - tasa) > _TOLERANCIA_PP:
            raise EstructuraInesperada(
                f"BCRD llegadas: {serie} {ultimo} crece {calculada:.4f} % y el BCRD publica "
                f"{tasa:.4f} %. La columna no es la verificada.")
    return series


class BCRDLlegadasClient(SourceClient):
    source = "BCRD (llegada de pasajeros no residentes vía aérea)"
    license = "datos oficiales BCRD — uso público con cita"
    license_ok = True
    fixture_file = "bcrd_lleg_no_residentes_2025_2026.xlsx"
    fixture_edicion = EdicionLlegadas(periodo="2026-07", publicada=date(2026, 8, 31))

    def __init__(self, mode: Mode = "fixture") -> None:
        super().__init__(mode)

    def _filas_live(self) -> Tuple[List[List[Any]], Optional[date]]:
        import httpx
        import xlrd

        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            r = http.get(URL_LLEGADAS)
            r.raise_for_status()
        publicada = None
        try:
            publicada = parsedate_to_datetime(r.headers["Last-Modified"]).astimezone(timezone.utc).date()
        except (KeyError, TypeError, ValueError):
            pass
        wb = xlrd.open_workbook(file_contents=r.content)
        nombre = next((n for n in wb.sheet_names() if _norm(n).startswith(_PREFIJO_HOJA)), None)
        if nombre is None:
            raise EstructuraInesperada(f"BCRD llegadas: sin hoja de no residentes ({wb.sheet_names()}).")
        hoja = wb.sheet_by_name(nombre)
        return [hoja.row_values(i) for i in range(hoja.nrows)], publicada

    def _filas_fixture(self) -> List[List[Any]]:
        import openpyxl

        wb = openpyxl.load_workbook(_FIXTURES_DIR / self.fixture_file, read_only=True, data_only=True)
        try:
            return [list(f) for f in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()

    def leer_ultima_edicion(self) -> Tuple[List[Record], EdicionLlegadas]:
        self.check_license()
        if self.mode == "fixture":
            filas, publicada = self._filas_fixture(), self.fixture_edicion.publicada
        else:
            filas, publicada = self._filas_live()
        series = parse_hoja_no_residentes(filas)
        edicion = EdicionLlegadas(periodo=max(series[SERIE_TOTAL]), publicada=publicada)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today(),
                          url=URL_LLEGADAS)
        registros = [Record(series=s, period=p, value=v, lineage=lineage, unit="personas")
                     for s, puntos in series.items() for p, v in sorted(puntos.items())]
        logger.info("[BCRD llegadas] %s (%s): %d puntos", edicion.periodo, self.mode, len(registros))
        return registros, edicion

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        registros, _ = self.leer_ultima_edicion()
        return [r for r in registros
                if (series is None or r.series == series) and (period is None or r.period == period)]


__all__ = ["BCRDLlegadasClient", "EdicionLlegadas", "EstructuraInesperada", "GRUPOS",
           "HOJA_NO_RESIDENTES", "SERIE_DOMINICANOS", "SERIE_EXTRANJEROS", "SERIE_TOTAL",
           "URL_LLEGADAS", "datetime", "parse_hoja_no_residentes"]
