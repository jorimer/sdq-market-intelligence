"""Catalog of recurring BCRD reports + how to find their PDFs on the CDN.

The BCRD hosts reports at predictable CDN paths, but file-naming differs per
report (clean ``YYYY-MM`` suffixes for IPOM/Economía Dominicana; irregular
``{Mes}{YYYY}`` for Estabilidad Financiera). Each :class:`ReportSpec` therefore
yields *candidate* (period, url) pairs newest-first; the service HEAD-probes them
and ingests the first that exists. Verified empirically 2026-06 (see PR notes).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

CDN = "https://cdn.bancentral.gov.do/documents"

_IPOM_DIR = f"{CDN}/publicaciones-economicas/informe-de-politica-monetaria/documents"
_INFECO_DIR = f"{CDN}/publicaciones-economicas/informe-de-la-economia-dominicana/documents"
_ESTAB_DIR = f"{CDN}/informe-de-estabilidad-financiera/documents"

_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre",
    12: "Diciembre",
}

# (period_label, url) — newest first within a year
Candidate = Tuple[str, str]


def _ipom_candidates(year: int) -> List[Candidate]:
    """Informe de Política Monetaria — trimestral desde 2026.

    El BCRD renombró el archivo en 2026 (``IPoM-{mes}-{año}.pdf``, mes en
    minúscula) y pasó de semestral a trimestral. 2025 y años previos conservan el
    nombre viejo ``informepm{año}-{mm}.pdf`` (solo junio / diciembre). Emitimos
    ambos patrones newest-first; el probe se queda con la primera URL que exista,
    así que no hace falta un año de corte hardcodeado. Verificado 2026-07 (marzo y
    junio 2026 con el patrón nuevo devuelven 200; el viejo, 404).
    """
    out: List[Candidate] = []
    for month in (12, 9, 6, 3):  # trimestres, más reciente primero
        out.append((f"{year}-{month:02d}", f"{_IPOM_DIR}/IPoM-{_MESES[month].lower()}-{year}.pdf"))
        if month in (12, 6):  # fallback histórico: naming viejo, cadencia semestral
            out.append((f"{year}-{month:02d}", f"{_IPOM_DIR}/informepm{year}-{month:02d}.pdf"))
    return out


def _infeco_candidates(year: int) -> List[Candidate]:
    """Informe de la Economía Dominicana — prefiere 'definitivo'; -12, -09, -06."""
    out: List[Candidate] = []
    for mm in ("12", "09", "06"):
        out.append((f"{year}-{mm}", f"{_INFECO_DIR}/infeco_definitivo{year}-{mm}.pdf"))
        out.append((f"{year}-{mm} (preliminar)", f"{_INFECO_DIR}/infeco_preliminar{year}-{mm}.pdf"))
    return out


def _estabilidad_candidates(year: int) -> List[Candidate]:
    """Informe de Estabilidad Financiera — naming irregular: {Mes}{YYYY} y {YYYY}."""
    out: List[Candidate] = []
    for month in (12, 9, 6, 3):
        mes = _MESES[month]
        out.append((f"{mes} {year}", f"{_ESTAB_DIR}/InformeEstabilidadFinanciera{mes}{year}.pdf"))
    out.append((f"{year}", f"{_ESTAB_DIR}/InformeEstabilidadFinanciera{year}.pdf"))
    return out


@dataclass(frozen=True)
class ReportSpec:
    key: str
    name: str
    cadence: str            # semestral | trimestral | anual | decenal | multianual
    sectors: Tuple[str, ...]  # relevance routing for insight enrichment
    landing_url: str        # human page (for the UI "ver en…" link)
    _candidates: Callable[[int], List[Candidate]]
    source: str = "BCRD"    # issuing institution (BCRD | ONE)

    def candidates(self, year: int) -> List[Candidate]:
        return self._candidates(year)


# ── ONE (Oficina Nacional de Estadística) ─────────────────────────
# ONE study PDFs live at one.gob.do/media/{opaque-hash}/{slug}.pdf — the hash is
# not derivable from a date, so each edition's URL is pinned (verified 2026-06-17).
_ONE = "https://www.one.gob.do/media"


def _fixed(*pairs: Candidate) -> Callable[[int], List[Candidate]]:
    """Candidate generator for a pinned-URL edition (date-independent)."""
    pinned = list(pairs)
    return lambda _year: pinned


REPORTS: Dict[str, ReportSpec] = {
    "estabilidad_financiera": ReportSpec(
        key="estabilidad_financiera",
        name="Informe de Estabilidad Financiera",
        cadence="semestral",
        sectors=("banca", "macro"),
        landing_url="https://www.bancentral.gov.do/a/d/4211-informe-de-estabilidad-financiera",
        _candidates=_estabilidad_candidates,
    ),
    "economia_dominicana": ReportSpec(
        key="economia_dominicana",
        name="Informe de la Economía Dominicana",
        cadence="semestral",
        sectors=("macro", "banca"),
        landing_url="https://www.bancentral.gov.do/a/d/2533-informe-de-la-economia-dominicana",
        _candidates=_infeco_candidates,
    ),
    "politica_monetaria": ReportSpec(
        key="politica_monetaria",
        name="Informe de Política Monetaria (IPOM)",
        cadence="trimestral",
        sectors=("macro",),
        landing_url="https://www.bancentral.gov.do/a/d/2535-informe-de-politica-monetaria",
        _candidates=_ipom_candidates,
    ),
    # ── ONE (Eje Social/ESG) — estudios y encuestas ──────────────
    "one_censo_2022": ReportSpec(
        key="one_censo_2022", source="ONE",
        name="X Censo Nacional de Población y Vivienda 2022",
        cadence="decenal", sectors=("social", "esg"),
        landing_url="https://www.one.gob.do/publicaciones/2024/informe-general-del-x-censo-nacional-de-poblacion-y-vivienda-2022/",
        _candidates=_fixed(("2022", f"{_ONE}/ahziolzm/informe-general-xcnpv-2022-digital.pdf")),
    ),
    "one_enhogar": ReportSpec(
        key="one_enhogar", source="ONE",
        name="ENHOGAR — Encuesta Nacional de Hogares de Propósitos Múltiples",
        cadence="multianual", sectors=("social",),
        landing_url="https://www.one.gob.do/publicaciones/2023/informe-general-enhogar-2022/",
        _candidates=_fixed(("2022", f"{_ONE}/my1fqfov/informe-general-enhogar-2022.pdf")),
    ),
    "one_pobreza": ReportSpec(
        key="one_pobreza", source="ONE",
        name="Boletín de Pobreza Monetaria",
        cadence="anual", sectors=("social",),
        landing_url="https://www.one.gob.do/publicaciones/2024/boletin-de-estadisticas-oficiales-de-pobreza-monetaria-en-republica-dominicana-2023/",
        _candidates=_fixed(("2023", f"{_ONE}/tm5paqul/pobreza-monetaria-en-la-rep%C3%BAblica-dominicana-2023elfinal.pdf")),
    ),
    "one_vitales": ReportSpec(
        key="one_vitales", source="ONE",
        name="Compendio de Estadísticas Vitales",
        cadence="anual", sectors=("social",),
        landing_url="https://www.one.gob.do/publicaciones/2026/compendio-de-estadisticas-vitales-2021-2025/",
        _candidates=_fixed(("2021-2025", f"{_ONE}/yrufxiag/compendio-de-estad%C3%ADsticas-vitales-2021-2025.pdf")),
    ),
    "one_anuario": ReportSpec(
        key="one_anuario", source="ONE",
        name="Anuario de Estadísticas Sociodemográficas",
        cadence="anual", sectors=("social", "esg"),
        landing_url="https://www.one.gob.do/datos-y-estadisticas/",
        _candidates=_fixed(("2024", f"{_ONE}/2gpfhhba/anuario-de-estad%C3%ADsticas-sociodemogr%C3%A1ficas-2024.pdf")),
    ),
}


def report_keys(source: str | None = None) -> List[str]:
    """Report keys, optionally filtered by issuing institution (BCRD | ONE)."""
    return [k for k, s in REPORTS.items() if source is None or s.source == source]


def candidate_urls(report_key: str, year: int, lookback_years: int = 0) -> List[Candidate]:
    """All candidate (period, url) for *report_key*, newest year first.

    ``lookback_years`` adds older years (for backfilling history).
    """
    spec = REPORTS[report_key]
    out: List[Candidate] = []
    for y in range(year, year - lookback_years - 1, -1):
        out.extend(spec.candidates(y))
    return out
