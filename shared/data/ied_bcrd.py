"""IED por actividad económica (BCRD) — el desenlace que el IAI SÍ pretende anticipar.

El Gate E sectorial validaba el IAI contra el crecimiento del EMPLEO formal y daba
nulo/negativo (IC medio anual −0,03; spread de quintiles −1,13 pp). El resultado es
correcto y el índice no: el IAI es un **Índice de Atractivo de INVERSIÓN**, y el empleo no
es lo que dice anticipar. Este conector trae el desenlace que sí le corresponde — la
inversión extranjera directa realizada por actividad, que el propio BCRD publica.

Fuente: BCRD, *Flujos de la Inversión Extranjera Directa por actividad económica*
(`inversion_ext_sector_6.xls`, hoja anual, 2010→, millones de US$). Dato público real.

**Nueve actividades, que no son los 17 sectores ni las 10 ramas de la ENCFT.** Es una
tercera resolución del mismo mapa, y como las otras se declara en vez de repartirse: ver
``shared.data.sector_crosswalk.IED_ACTIVITIES``. La cobertura es PARCIAL —la IED no llega a
agropecuario, construcción, administración pública, enseñanza, salud ni servicios
profesionales— y esos sectores quedan fuera del panel de este desenlace. Imputarles cero
sería afirmar que no recibieron inversión, cuando lo que pasa es que la fuente no los
publica.

Guards fail-closed, en la línea del conector de empleo:
  * una fila que parece actividad y no mapea → el BCRD renombró algo → se levanta.
  * ninguna actividad reconocida → se levanta (no se devuelve un panel vacío en silencio).
  * Σ actividades tiene que cuadrar con la fila ``Total`` del propio cuadro cada año, con
    tolerancia por redondeo → se levanta si se desvía. Es la lección de verificar contra
    una magnitud REAL de la fuente y no contra una invariante interna.

Los valores NEGATIVOS son legítimos y se conservan: una desinversión neta es información,
no un error de lectura.
"""
import io
import logging
from datetime import date
from typing import Dict, List, Optional

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage
from shared.data.sector_crosswalk import IED_KEYS, map_ied_label

logger = logging.getLogger("sdq.data.ied_bcrd")

LICENSE = "open-data"
SOURCE = "BCRD"
SERIES = "ied_usd_mm"
UNIT = "millones de US$"

WORKBOOK_URL = (
    "https://cdn.bancentral.gov.do/documents/estadisticas/sector-externo/"
    "documents/inversion_ext_sector_6.xls"
)
ANNUAL_SHEET = "IED por actividad anual"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sdq-mip/1.0)"}

# Filas que NO son actividades: el total del cuadro y el cajón de sastre que el BCRD
# publica en cero. Meterlas al panel agregaría un total dentro de lo que se ordena.
_TOTAL_LABEL = "total flujos ied"
_NO_ACTIVIDAD = ("otros",)

# Tolerancia del cuadre contra el Total del cuadro: el BCRD publica con un decimal y la
# suma de nueve filas redondeadas se desvía por centésimas.
_TOLERANCIA_CUADRE = 1.0


class IedError(RuntimeError):
    """El cuadro de IED cambió de forma y la lectura no es confiable."""


def _norm(v: object) -> str:
    from shared.data._text import norm

    return norm(v)


def _year(v: object) -> Optional[str]:
    """Encabezado de columna → año de cuatro dígitos, o None si no lo es."""
    try:
        y = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None
    return str(y) if 1990 <= y <= 2100 else None


def parse_annual_sheet(rows: List[List[object]]) -> Dict[str, Dict[str, Optional[float]]]:
    """Filas crudas de la hoja anual → ``{actividad: {año: valor}}``, con los guards.

    Pura y testeable: recibe la matriz ya leída, no el archivo.
    """
    # La fila de años es la que MÁS años tiene, no la primera con algunos: un valor de IED
    # como 2023,7 millones parece un año, y elegir por umbral bajo podría tomar una fila de
    # datos como encabezado. El encabezado real trae una columna por año.
    conteos = [(sum(1 for c in r[1:] if _year(c)), i) for i, r in enumerate(rows)]
    mejor, idx_años = max(conteos) if conteos else (0, None)
    if not mejor or mejor < 2 or idx_años is None:
        raise IedError("no se encontró la fila de años en la hoja anual de IED")
    columnas: Dict[int, str] = {}
    for i, c in enumerate(rows[idx_años]):
        if i > 0 and (año := _year(c)):
            columnas[i] = año

    datos: Dict[str, Dict[str, Optional[float]]] = {}
    total_por_año: Dict[str, float] = {}
    for i_fila, r in enumerate(rows):
        if i_fila <= idx_años:
            continue  # el encabezado («Actividad Económica») y todo lo que va arriba
        etiqueta = str(r[0]).strip() if r and r[0] is not None else ""
        if not etiqueta or etiqueta.lower() == "nan":
            continue
        n = _norm(etiqueta)
        if n == _TOTAL_LABEL:
            for i, año in columnas.items():
                v = _num(r[i] if i < len(r) else None)
                if v is not None:
                    total_por_año[año] = v
            continue
        if n in _NO_ACTIVIDAD or n.startswith(("nota", "estadisticas", "fuente", "banco central",
                                               "departamento", "flujos de la inversion",
                                               "millones de us")):
            continue
        clave = map_ied_label(etiqueta)
        if clave is None:
            # Una fila con años a su derecha y sin mapa es una actividad que el BCRD
            # renombró o agregó: seguir sería publicar un panel incompleto en silencio.
            if any(_num(r[i] if i < len(r) else None) is not None for i in columnas):
                raise IedError(
                    f"actividad de IED no reconocida en el cuadro del BCRD: «{etiqueta}». "
                    f"Actualizá `IED_ACTIVITIES` en shared/data/sector_crosswalk.py."
                )
            continue
        datos[clave] = {año: _num(r[i] if i < len(r) else None) for i, año in columnas.items()}

    if not datos:
        raise IedError("la hoja anual de IED no produjo ninguna actividad reconocida")

    _verificar_cuadre(datos, total_por_año)
    return datos


def _num(v: object) -> Optional[float]:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, 4)  # NaN → None


def _verificar_cuadre(datos: Dict[str, Dict[str, Optional[float]]],
                      total: Dict[str, float]) -> None:
    """Σ actividades ≈ Total del cuadro, por año. Contra la magnitud REAL de la fuente."""
    desvios = []
    for año, esperado in total.items():
        suma = sum(v for a in datos.values() if (v := a.get(año)) is not None)
        if abs(suma - esperado) > _TOLERANCIA_CUADRE:
            desvios.append(f"{año}: Σ={suma:.1f} vs Total={esperado:.1f}")
    if desvios:
        raise IedError(
            "la suma de actividades no cuadra con el Total del propio cuadro del BCRD "
            f"({'; '.join(desvios[:5])}). La lectura no es confiable."
        )


class IedBcrdClient(FixtureBackedClient):
    """IED por actividad económica del BCRD (desenlace del Gate E sectorial)."""

    source = SOURCE
    license = LICENSE
    license_ok = True
    fixture_file = "ied_bcrd.json"
    live_phase = "Gate E sectorial · desenlace de inversión"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        datos = self._fetch_live() if self.mode == "live" else self._fetch_fixture()
        lineage = Lineage(source=SOURCE, license=LICENSE, fetched_at=date.today())
        salida: List[Record] = []
        for actividad in IED_KEYS:
            for año, valor in sorted((datos.get(actividad) or {}).items()):
                if period and año != period:
                    continue
                salida.append(Record(series=SERIES, period=año, value=valor, unit=UNIT,
                                     lineage=lineage, dimension=actividad,
                                     reason=None if valor is not None
                                     else "el BCRD no publica el valor para ese año"))
        return salida

    # ── Live ────────────────────────────────────────────────────────
    def _fetch_live(self) -> Dict[str, Dict[str, Optional[float]]]:  # pragma: no cover - red
        import httpx
        import pandas as pd

        resp = httpx.get(WORKBOOK_URL, timeout=90, follow_redirects=True, headers=_HEADERS)
        resp.raise_for_status()
        libro = pd.ExcelFile(io.BytesIO(resp.content))
        if ANNUAL_SHEET not in libro.sheet_names:
            raise IedError(
                f"el cuadro de IED ya no trae la hoja «{ANNUAL_SHEET}» "
                f"(hojas: {libro.sheet_names})"
            )
        df = libro.parse(ANNUAL_SHEET, header=None)
        return parse_annual_sheet(df.values.tolist())

    # ── Fixture ─────────────────────────────────────────────────────
    def _fetch_fixture(self) -> Dict[str, Dict[str, Optional[float]]]:
        return self._load_fixture(self.fixture_file)


ied_bcrd_client = IedBcrdClient(mode="live")
