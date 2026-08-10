"""Oficina Nacional de Estadística (ONE) — live connector for social data.

Feeds Eje 6 (`social_dev`) with real ONE statistics. First dataset wired: the
*Tasa de Pobreza Monetaria General y Extrema por Regiones de Desarrollo* (the one
IDM variable ONE publishes structured and by the 10 development regions), CSV from
``descargas.one.gob.do``, 2000-…. Other ONE datasets (services, education) are
added to ``DATASETS`` over time; the studies in PDF (Censo/ENHOGAR) go through the
publications-digest path, not here.

``Record.dimension`` carries the region slug (no separate field), mirroring how
:mod:`shared.data.bcrd_sectors` carries the sector slug. Missing values stay
``None`` — never interpolated. ``live`` mode downloads the CSV; ``fixture`` mode
reads ``one.json`` for offline/tests.

A second dataset is wired below as a plain module function (not the ``Record``
client): the national years-of-schooling series, scraped from the ONE portal by
media-hash (the DGA pattern) and parsed from its *Indicador* sheet.

QUÉ SIGUE VIVO ACÁ Y QUÉ SE FUE (importante antes de tocar este módulo)
----------------------------------------------------------------------
El portal ``www.one.gob.do`` quedó detrás de un desafío de Cloudflare y devuelve
403 a cualquier cliente que no sea un navegador — también desde producción. Lo
que raspa ese portal está, hoy, **caído**: no falla en silencio, declara el
motivo en ``errors`` de la operación (ver ``modules/social_dev/social_sync.py``).

* **Vivo y sano** — el CSV de pobreza por regiones (``ONEClient``). Va por
  ``descargas.one.gob.do``, que es otro host y sigue abierto. Y el padrón de
  regiones (``REGIONS`` / :func:`region_slug`), que es la misma verdad para
  cualquier emisor que las nombre: lo consumen conectores de otras fuentes.
* **Vivo pero caído** — ``fetch_one_education_schooling`` (años promedio de
  escolaridad). Es lo ÚNICO que queda colgando del portal: el ENHOGAR solo
  publica alfabetización por región, no años de estudio, así que no tiene
  sustituto conocido y se queda hasta que aparezca uno o vuelva el portal.
* **Se fue** — informalidad → :mod:`shared.data.bcrd_labor` (ENCFT del BCRD);
  cobertura educativa → :mod:`shared.data.minerd_coverage` (tablero SIIE del
  MINERD); ingreso → :mod:`shared.data.sisdom_income` (SISDOM del MEPyD). En los
  tres casos la ONE no producía el dato: lo republicaba, y el reemplazo dejó cada
  serie mejor de lo que estaba (fuente primaria, más cobertura, y en el ingreso
  además apertura POR REGIÓN donde antes había una constante nacional).

Los caminos muertos se **borraron** en vez de guardarse como reserva: a una
reserva tras Cloudflare no se puede llegar, y dejar dos lecturas de un mismo
indicador —una muerta— invita a recablear la equivocada. El historial las
conserva (``git log -- shared/data/one_client.py``).
"""
import csv
import io
import logging
import re
import unicodedata
from datetime import date
from html import unescape
from typing import Dict, List, Optional

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.one")

# Poverty dataset (datos.gob.do org ONE) — public CSV on the ONE download CDN.
POVERTY_URL = (
    "https://descargas.one.gob.do/download/OGTIC/"
    "Tasa_de_Pobreza_Monetaria_General_y_Extrema_por_Regiones_de_Desarrollo,_2000-2024.csv"
)
# CSV columns: "Tasa de Pobreza" {Pobreza Extrema|General} · region · "Porcentaje" · "Año".
POVERTY_GENERAL = "pobreza general"
POVERTY_EXTREME = "pobreza extrema"

# The 10 development regions → stable slugs. Source labels vary in leading spaces
# / "Ozama o Metropolitana", so we match on a normalized key.
REGIONS: List[tuple] = [
    ("cibao_norte", "Cibao Norte"),
    ("cibao_sur", "Cibao Sur"),
    ("cibao_nordeste", "Cibao Nordeste"),
    ("cibao_noroeste", "Cibao Noroeste"),
    ("valdesia", "Valdesia"),
    ("enriquillo", "Enriquillo"),
    ("el_valle", "El Valle"),
    ("higuamo", "Higuamo"),
    ("ozama", "Ozama o Metropolitana"),
    ("yuma", "Yuma"),
]


def _norm(s: object) -> str:
    """Accent/case/space-insensitive key for matching provider labels."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


# Known label variants the provider has used for the same region → slug. Ozama
# (Gran Santo Domingo, the most populous region) circulates under several names;
# a single-token rename must not silently drop it (matching is exact-normalized,
# not token-subset). Extend here if the ONE renames a region.
_REGION_ALIASES: Dict[str, str] = {
    "ozama": "ozama",
    "metropolitana": "ozama",
    "gran santo domingo": "ozama",
}
_REGION_BY_NORM: Dict[str, str] = {_norm(label): slug for slug, label in REGIONS}
_REGION_BY_NORM.update({_norm(k): v for k, v in _REGION_ALIASES.items()})


def region_catalog() -> List[tuple]:
    """``[(slug, display_name)]`` for seeding the region peer set."""
    return [(slug, label) for slug, label in REGIONS]


def _parse_poverty_csv(raw: bytes) -> List[tuple]:
    """Parse the poverty CSV → ``[(theme, region_slug, year, value)]``.

    ``theme`` is ``poverty_rate`` (general) or ``poverty_extreme``. Rows whose
    region isn't a known development region are skipped (logged), never guessed.
    """
    text = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("CSV de pobreza ONE: no se pudo decodificar")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    out: List[tuple] = []
    unknown = set()
    for r in rows[1:]:
        if len(r) < 4:
            continue
        kind = _norm(r[0])
        slug = _REGION_BY_NORM.get(_norm(r[1]))
        year = r[3].strip()
        if slug is None:
            unknown.add(r[1].strip())
            continue
        if not year.isdigit():
            continue
        try:
            value = float(r[2].replace(",", "").strip())
        except ValueError:
            continue
        if kind == POVERTY_GENERAL:
            out.append(("poverty_rate", slug, year, value))
        elif kind == POVERTY_EXTREME:
            out.append(("poverty_extreme", slug, year, value))
    if unknown:
        logger.warning("[ONE] regiones no reconocidas en el CSV de pobreza: %s", sorted(unknown))
    return out


class ONEClient(FixtureBackedClient):
    """ONE social statistics (Eje 6). Live = download the configured CSVs."""

    source = "ONE"
    license = "datos oficiales ONE — uso público con cita"
    license_ok = True
    fixture_file = "one.json"
    live_phase = "Fase 4 (Eje 6 · social)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return self._fetch_fixture(series, period)

    # ── Live ──────────────────────────────────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        import httpx

        resp = httpx.get(POVERTY_URL, timeout=40, follow_redirects=True)
        resp.raise_for_status()
        published = self._published_at(resp)
        lineage = Lineage(
            source="ONE", license=self.license, fetched_at=date.today(),
            published_at=published, url=POVERTY_URL,
            note="Tasa de pobreza monetaria por regiones de desarrollo",
        )
        out: List[Record] = []
        for theme, slug, year, value in _parse_poverty_csv(resp.content):
            out.append(Record(series=theme, period=year, value=value,
                              lineage=lineage, unit="% de la población", dimension=slug))
        return _filter(out, series, period)

    @staticmethod
    def _published_at(resp) -> Optional[date]:  # pragma: no cover - network I/O
        from datetime import datetime

        lm = resp.headers.get("last-modified")
        if not lm:
            return None
        try:
            return datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z").date()
        except ValueError:
            return None

    # ── Fixture (offline / tests) ─────────────────────────────────
    def _fetch_fixture(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Fixture shape: ``{"<slug>": {"<theme>": {"<year>": value}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for slug, themes in fixture.items():
            for theme, obs in themes.items():
                for yr, val in obs.items():
                    out.append(Record(
                        series=theme, period=str(yr),
                        value=None if val is None else float(val),
                        lineage=lineage, unit="% de la población", dimension=slug,
                    ))
        return _filter(out, series, period)


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


one_client = ONEClient()


# ── Descubrimiento de archivos en el portal de la ONE ──────────────────────
# Los archivos viven en el CDN Umbraco de la ONE bajo ``/media/<hash>/<slug>.xlsx``
# (el patrón media-hash de la DGA); el hash rota, así que se raspa la landing del tema
# para los enlaces vigentes. Hoy queda UN solo consumidor: la escolaridad.
_MEDIA_XLSX_RE = re.compile(r"/media/[a-z0-9]+/[^\"'> ]+?\.xlsx", re.IGNORECASE)
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP ONE labour connector)"}


def _end_year(path: str) -> int:
    """Highest 4-digit year in a filename (its coverage end), or 0."""
    return max((int(y) for y in re.findall(r"(?:19|20)\d{2}", path)), default=0)


def _match_media_links(html_text: str, slugs: Dict[str, str]) -> Dict[str, str]:
    """``{key: /media/<hash>/<slug>.xlsx}`` matching each *slugs* fragment in the HTML.

    Accent/case-insensitive (so a rotated media hash is followed automatically);
    when several revisions match the same slug (e.g. ``…-2004-2023`` and
    ``…-2004-2024``) the latest end-year wins (deterministic, like the DGA ``-v2``
    tie-break). A file that isn't found is simply absent (never fabricated)."""
    best: Dict[str, tuple] = {}  # key -> (end_year, url)
    for raw in sorted({unescape(m) for m in _MEDIA_XLSX_RE.findall(html_text)}):
        norm = _norm(raw)
        for key, slug in slugs.items():
            if slug in norm:
                ey = _end_year(raw)
                if key not in best or ey > best[key][0]:
                    best[key] = (ey, raw)
    return {key: url for key, (_ey, url) in best.items()}


def parse_one_indicator_xlsx(content: bytes) -> List[tuple]:
    """Parse an ONE *Indicador* sheet → ``[(year, value)]`` from the Total column.

    The file's first sheet is a *Ficha técnica* (metadata); the series lives in
    the ``Indicador`` sheet as ``Año | Total | Hombres | Mujeres``. Year rows are
    found by a 4-digit year in column A; missing/non-numeric stays out."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    # Sheet names often carry trailing spaces/case; fall back to the last sheet.
    sheet = next((n for n in wb.sheetnames if n.strip().casefold() == "indicador"), None)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[-1]]
    out: List[tuple] = []
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        a, total = row[0], (row[1] if len(row) > 1 else None)
        if isinstance(a, (int, float)) and 1990 <= int(a) <= 2100 and isinstance(total, (int, float)):
            out.append((int(a), round(float(total), 4)))
    return out


# ── ONE education — national years of schooling ────────────────────────────
# La COBERTURA educativa ya no sale de acá: la produce el MINERD y se lee de su
# tablero SIIE (:mod:`shared.data.minerd_coverage`), que además llega al año lectivo
# 2024-2025 y trae región y provincia en la misma fila.
EDUCATION_LANDING = (
    "https://www.one.gob.do/datos-y-estadisticas/temas/estadisticas-sociales/educacion/"
)
# National average years of schooling (15+) — the IDM's schooling_years (ENHOGAR
# only reports literacy by region, not years of schooling). Simple Año|Total sheet.
_SCHOOLING_SLUG = "anos-promedio-de-educacion-de-la-poblacion-de-15-anos-y-mas"


def region_slug(label: object) -> Optional[str]:
    """Slug de la región de desarrollo para una etiqueta del proveedor, o ``None``.

    Público porque el padrón de regiones —con sus alias, ver ``_REGION_ALIASES``— es la
    misma verdad para CUALQUIER fuente que las nombre: hoy lo usa el conector del
    MINERD, que es de otro emisor. Tolera el prefijo "Región " y las variantes de
    Ozama."""
    n = _norm(label).replace("region ", "", 1).strip()
    return _REGION_BY_NORM.get(n)


def fetch_one_education_schooling() -> List[tuple]:  # pragma: no cover - network I/O
    """Live: national average years of schooling (15+) from the Educación landing →
    ``[(year, value)]`` (the IDM's ``schooling_years``, national).

    Mismo estado que :func:`fetch_one_labor`: el portal responde 403 (Cloudflare) y la
    falla se DECLARA, no se esconde. Sigue acá por la misma razón — sin sustituto."""
    import urllib.parse

    import httpx

    resp = httpx.get(EDUCATION_LANDING, timeout=40, follow_redirects=True, headers=_HEADERS)
    resp.raise_for_status()
    path = _match_media_links(resp.text, {"schooling_years": _SCHOOLING_SLUG}).get("schooling_years")
    if not path:
        return []
    f = httpx.get("https://www.one.gob.do" + urllib.parse.quote(path), timeout=60,
                  follow_redirects=True, headers=_HEADERS)
    f.raise_for_status()
    return parse_one_indicator_xlsx(f.content)
