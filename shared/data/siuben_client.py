"""SIUBEN — conector provincial (32 provincias, trimestral).

La primera fuente SUB-NACIONAL real del eje social. Las estadísticas sociales de la
ONE llegan como máximo a las 10 regiones de desarrollo —la muestra de la ENCFT está
diseñada para estimar por región, no por provincia—, así que la granularidad
provincial tenía que venir de otro lado. El Sistema Único de Beneficiarios publica en
``datos.gob.do`` cinco tableros por provincia con historia trimestral desde 2017.

**El universo, y por qué importa decirlo.** El SIUBEN no encuesta a la población
general: levanta el padrón de focalización de hogares pobres y vulnerables. Una cifra
de acá NO es "la tasa de X de la provincia" sino "la composición del padrón registrado
en la provincia". Es un indicador estructural legítimo y varía mucho entre
demarcaciones, pero un consumidor que lo lea como tasa poblacional se equivoca. Por eso
los códigos de serie llevan el prefijo ``siuben_`` y el sufijo ``_share``: el nombre
carga el caveat, no una nota al pie que alguien no lee.

El tablero de ICV además cubre SOLO a las personas con discapacidad del padrón —un
subconjunto del subconjunto—; su código lo dice (``siuben_disability_icv1_share``).

Diseño de robustez, igual que el parser de cobertura de la ONE:

* Los recursos se **descubren por CKAN** (el id numérico de ``siuben.gob.do`` rota).
* Las columnas se localizan **por encabezado**, nunca por posición fija.
* La proporción se **recalcula desde los conteos**, no se suman los porcentajes
  publicados: así el denominador es explícito y componer categorías (hacinamiento
  extremo + moderado) no arrastra error de redondeo.
* Una provincia que no se reconoce se **descarta y se cuenta** (ver
  ``shared.reference.provinces``), jamás se reparte a la más parecida.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sdq.data.siuben")

CKAN_SEARCH = "https://datos.gob.do/api/3/action/package_search"
SIUBEN_ORG = "sistema-unico-de-beneficiarios-siuben"
SOURCE = "SIUBEN"
LICENSE = "datos abiertos del Estado dominicano (datos.gob.do) — uso público con cita"
# Rótulo que viaja con cada observación: el universo, no una nota al pie.
UNIVERSE = "padrón SIUBEN (hogares registrados)"

_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP SIUBEN connector)"}

# Encabezados que NO son una categoría contable (todo lo demás en la fila de
# encabezado se toma como una categoría con su conteo).
_NON_CATEGORY = ("provincia", "porcentaje", "periodo", "ano", "a o", "total")

_QUARTERS = {"enero": "Q1", "abril": "Q2", "julio": "Q3", "octubre": "Q4"}


@dataclass(frozen=True)
class SiubenDataset:
    """Un tablero provincial del SIUBEN y la proporción que derivamos de él."""

    theme: str                       # código de serie canónico
    resource_match: str              # fragmento del NOMBRE del recurso en CKAN
    numerator: Tuple[str, ...]       # fragmentos de encabezado que suman al numerador
    unit: str
    note: str


# Los cinco tableros. El numerador se declara por FRAGMENTO de encabezado normalizado:
# si el emisor renombra una categoría, el fragmento deja de calzar y la serie queda
# vacía (visible), en vez de sumar la columna equivocada en silencio.
DATASETS: Tuple[SiubenDataset, ...] = (
    SiubenDataset(
        theme="siuben_illiteracy_head_share",
        resource_match="jefes",
        numerator=("no sabe leer",),
        unit="% de jefes/as del padrón",
        note="Jefes/as de hogar del padrón SIUBEN que no saben leer ni escribir.",
    ),
    SiubenDataset(
        theme="siuben_overcrowding_share",
        resource_match="hacinamiento",
        numerator=("hacinamiento extremo", "hacinamiento moderado"),
        unit="% de hogares del padrón",
        note="Hogares del padrón con hacinamiento extremo o moderado.",
    ),
    SiubenDataset(
        theme="siuben_precarious_housing_share",
        resource_match="estructura de vivienda",
        numerator=("pieza en cuarter", "barrac", "otro tipo"),
        unit="% de hogares del padrón",
        note="Hogares del padrón en pieza de cuartería, barracón u otra estructura.",
    ),
    SiubenDataset(
        theme="siuben_unregistered_minors_share",
        resource_match="menores",
        numerator=("no tiene acta", "no fue declarado"),
        unit="% de menores del padrón",
        note=("Menores de 18 del padrón sin acta de nacimiento o no declarados — "
              "cobertura de registro civil."),
    ),
    SiubenDataset(
        theme="siuben_disability_icv1_share",
        resource_match="discapacidad",
        numerator=("icv 1",),
        unit="% de personas con discapacidad",
        note=("Personas CON DISCAPACIDAD del padrón en la categoría ICV-1 (la más "
              "carenciada). Subconjunto del padrón: no es la pobreza de la provincia."),
    ),
)


def _norm(s: object) -> str:
    """Clave insensible a acento/caso/puntuación para calzar encabezados y etiquetas."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(c if (c.isalnum() or c.isspace()) else " " for c in t)
    return " ".join(t.casefold().split())


def _decode(raw: bytes) -> str:
    """Los CSV del SIUBEN alternan UTF-8 y páginas de código DOS entre archivos."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _number(cell: object) -> Optional[float]:
    """``'1,374'`` → ``1374.0``; vacío / no numérico → ``None`` (nunca 0)."""
    text = str(cell or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_period(periodo: object, anio: object) -> Optional[str]:
    """``('Abril -  Junio', '2024')`` → ``'2024-Q2'``.

    El emisor escribe el trimestre con espaciado inconsistente (``Abril -Junio``,
    ``Abril -  Junio``), así que el trimestre se deduce del PRIMER mes nombrado."""
    year = str(anio or "").strip()
    if not re.fullmatch(r"(19|20)\d{2}", year):
        return None
    text = _norm(periodo)
    for month, q in _QUARTERS.items():
        if text.startswith(month):
            return f"{year}-{q}"
    return None


def _category_columns(header: Sequence[object]) -> List[Tuple[int, str]]:
    """``[(índice, encabezado normalizado)]`` de las columnas de CONTEO.

    Una columna es categoría si su encabezado no es provincia/porcentaje/período/año.
    Localizar por encabezado —y no por posición— es lo que impide que un cambio de
    layout del emisor nos haga leer la columna equivocada sin enterarnos."""
    out: List[Tuple[int, str]] = []
    for i, cell in enumerate(header):
        key = _norm(cell)
        if not key or any(key.startswith(bad) for bad in _NON_CATEGORY):
            continue
        out.append((i, key))
    return out


def parse_siuben_csv(text: str, spec: SiubenDataset) -> List[Tuple[str, str, float]]:
    """Parsea un CSV del SIUBEN → ``[(province_slug, period, share_pct)]``.

    La proporción se recalcula: ``numerador / total de las categorías × 100``. Pura
    (sin red) para poder fijarla en tests. Una fila sin provincia reconocida, sin
    período válido o con denominador cero se descarta y se registra."""
    from shared.reference.provinces import province_slug

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return []
    header = rows[0]
    cats = _category_columns(header)
    num_cols = [i for i, key in cats if any(frag in key for frag in spec.numerator)]
    if not cats or not num_cols:
        logger.warning(
            "[SIUBEN] %s: no se ubicaron las columnas del numerador %s en %s "
            "(¿cambió el layout?)", spec.theme, spec.numerator, [k for _i, k in cats])
        return []

    out: List[Tuple[str, str, float]] = []
    unknown: set = set()
    dropped = 0
    for row in rows[1:]:
        if len(row) < 3:
            continue
        slug = province_slug(row[0])
        if slug is None:
            if str(row[0] or "").strip():
                unknown.add(str(row[0]).strip())
            continue
        period = parse_period(row[-2], row[-1])
        if period is None:
            dropped += 1
            continue
        total = 0.0
        numerator = 0.0
        complete = True
        for i, _key in cats:
            v = _number(row[i]) if i < len(row) else None
            if v is None:
                complete = False
                break
            total += v
            if i in num_cols:
                numerator += v
        # Un denominador incompleto o cero no se rellena con supuestos: la fila cae.
        if not complete or total <= 0:
            dropped += 1
            continue
        out.append((slug, period, round(100.0 * numerator / total, 3)))
    if unknown:
        logger.warning("[SIUBEN] %s: provincias no reconocidas (descartadas): %s",
                       spec.theme, sorted(unknown))
    if dropped:
        logger.info("[SIUBEN] %s: %d filas descartadas (período o conteos incompletos)",
                    spec.theme, dropped)
    return out


def discover_resources(packages: Sequence[dict]) -> Dict[str, str]:
    """``{theme: url_del_CSV}`` a partir de la respuesta de CKAN.

    Se calza por NOMBRE del recurso (el id numérico de ``siuben.gob.do`` rota entre
    revisiones) y se exige formato CSV. Un tablero que no aparece simplemente falta:
    nunca se inventa una URL. Pura, para poder fijarla en tests."""
    by_theme: Dict[str, str] = {}
    for pkg in packages or ():
        for res in pkg.get("resources") or ():
            if _norm(res.get("format")) != "csv":
                continue
            name = _norm(res.get("name"))
            url = res.get("url")
            if not url:
                continue
            for spec in DATASETS:
                if spec.theme in by_theme:
                    continue
                if _norm(spec.resource_match) in name:
                    by_theme[spec.theme] = url
    missing = [s.theme for s in DATASETS if s.theme not in by_theme]
    if missing:
        logger.warning("[SIUBEN] recursos no encontrados en CKAN: %s", missing)
    return by_theme


class SiubenUnavailable(RuntimeError):
    """Ningún tablero pudo leerse. Lleva el motivo, no solo el hecho."""


def fetch_siuben_provincial() -> List[Tuple[str, str, str, float]]:  # pragma: no cover - network I/O
    """Live: descubre por CKAN, descarga y parsea los cinco tableros →
    ``[(theme, province_slug, period, value)]``.

    **Tolerante en lo parcial, ruidoso en lo total.** Que un tablero falle no debe
    tumbar a los otros cuatro; que fallen TODOS no es un resultado vacío legítimo, es una
    caída — y se levanta :class:`SiubenUnavailable` con los motivos acumulados.

    La distinción importa porque la primera versión devolvía ``[]`` en ambos casos, y
    aguas arriba eso se leyó como "la fuente no publicó nada". Un conector que se traga
    la razón obliga a ir a buscarla a los logs del contenedor, que es justo donde nadie
    mira (pasó el 2026-08-09)."""
    import httpx

    try:
        resp = httpx.get(CKAN_SEARCH, params={"fq": f"organization:{SIUBEN_ORG}", "rows": 50},
                         timeout=45, follow_redirects=True, headers=_HEADERS)
        resp.raise_for_status()
        packages = resp.json().get("result", {}).get("results", [])
    except (httpx.HTTPError, ValueError) as e:
        raise SiubenUnavailable(
            f"el catálogo CKAN de datos.gob.do no respondió ({type(e).__name__}: {e})")

    urls = discover_resources(packages)
    if not urls:
        raise SiubenUnavailable(
            f"CKAN respondió con {len(packages)} paquete(s) del SIUBEN pero ninguno "
            "expuso un recurso CSV de los cinco tableros esperados (¿renombraron los "
            "recursos?)")

    out: List[Tuple[str, str, str, float]] = []
    reasons: List[str] = []
    for spec in DATASETS:
        url = urls.get(spec.theme)
        if not url:
            reasons.append(f"{spec.theme}: sin recurso CSV en CKAN")
            continue
        try:
            f = httpx.get(url, timeout=90, follow_redirects=True, headers=_HEADERS)
            f.raise_for_status()
            rows = parse_siuben_csv(_decode(f.content), spec)
        except (httpx.HTTPError, ValueError) as e:
            reasons.append(f"{spec.theme}: {type(e).__name__}: {e}")
            continue
        if not rows:
            reasons.append(f"{spec.theme}: descargado pero sin filas utilizables")
            continue
        out.extend((spec.theme, slug, period, value) for slug, period, value in rows)

    if not out:
        raise SiubenUnavailable("ningún tablero pudo leerse — " + " · ".join(reasons))
    if reasons:
        logger.warning("[SIUBEN] tableros con problema (%d de %d): %s",
                       len(reasons), len(DATASETS), " · ".join(reasons))
    return out


def theme_spec(theme: str) -> Optional[SiubenDataset]:
    """El descriptor de una serie SIUBEN (unidad y nota), para el sync y la Data API."""
    return next((s for s in DATASETS if s.theme == theme), None)
