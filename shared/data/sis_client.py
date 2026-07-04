"""Superintendencia de Seguros (SIS) — connector for Dominican insurance data.

Like SIPEN, SIS data has two natures, exposed behind the platform's ``Record``
contract:

  * **Market / national** series (the insurance market as a whole): net premiums
    collected by ramo (line of business), and the count of insurers active per
    ramo. One value per period — these feed the anonymized market **Pulse**.
  * **Entity** series (per insurer — solvency, liquidity, AUM from audited
    financial statements). These land in F1b, carried per-entity via the audited
    Excel-per-company + InDataRD Power BI channels — modeled on banking_score.

Real publication channels (F0 discovery, 2026-07-03):
  A) CKAN ``datos.gob.do`` — *Primas Netas Cobradas según Ramo* (2020-2025) and
     *Ramos de Compañías de Seguros* (2018-2025), as direct XLSX/CSV. **live path.**
  B) SIS site — *Estados Financieros Auditados por cía* (Excel), *Índices de
     Solvencia y Liquidez* (InDataRD = Power BI publish-to-web). **F1b.**

The SIS site HTML blocks non-browser clients (HTTP 473), but the CKAN API and the
direct file URLs answer fine from the backend — so ``live`` mode downloads the
CKAN XLSX and parses it. ``fixture`` mode reads a committed, real, cited sample
(``sis.json``, the full monthly premium series 2020-2025). Missing values stay
``None`` — never interpolated.

DATA CAVEAT (from source, surfaced honestly): in the published premium file the
year **2024 is an exact duplicate of 2023** (a publication placeholder — the file
was uploaded 2024/08 before 2024 closed). Consumers treat 2024 as non-independent
and read growth 2023 → 2025.
"""
import io
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sis")

# ── CKAN resources (direct file URLs, verified live 2026-07-03) ──────────────
_CKAN_PRIMAS_XLSX = (
    "https://sis.gob.do/wp-content/uploads/2024/08/"
    "Primas-Netas-Cobradas-segun-Ramo-2020-%E2%80%93-2025.xlsx"
)
_CKAN_RAMOS_XLSX = (
    "https://sis.gob.do/wp-content/uploads/2024/08/"
    "Ramos-de-Companias-de-Seguros-SIS-2018-%E2%80%93-2025.xlsx"
)
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"

_MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05",
    "junio": "06", "julio": "07", "agosto": "08", "septiembre": "09",
    "octubre": "10", "noviembre": "11", "diciembre": "12",
}

# Ramo (line of business) display labels, keyed by slug. Stable order = market weight.
RAMO_LABELS: List[Tuple[str, str]] = [
    ("vida_individual", "Vida Individual"),
    ("vida_colectiva", "Vida Colectiva"),
    ("salud", "Salud"),
    ("accidentes_pers", "Accidentes Personales"),
    ("incendio_y_aliados", "Incendio y Aliados"),
    ("naves_marit_y_aerea", "Naves Marítimas y Aéreas"),
    ("transporte_de_carga", "Transporte de Carga"),
    ("vehiculos_de_motor", "Vehículos de Motor"),
    ("agricola_y_pecuario", "Agrícola y Pecuario"),
    ("fianzas", "Fianzas"),
    ("otros", "Otros"),
]


def ramo_catalog() -> List[Tuple[str, str]]:
    """The ramos (lines of business) SIS reports, as ``[(slug, label)]``."""
    return list(RAMO_LABELS)


def _slugify(name: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


class SISClient(FixtureBackedClient):
    """SIS insurance-market connector. ``fixture`` mode is the default and ships
    the real committed sample; ``live`` mode downloads + parses the CKAN XLSX."""

    source = "SIS"
    # ODbL — Open Data Commons Open Database License (as declared on datos.gob.do).
    license = "https://opendatacommons.org/licenses/odbl/"
    license_ok = True
    fixture_file = "sis.json"
    live_phase = "F1a (CKAN live)"

    # ── Live CKAN download + parse ────────────────────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Download the CKAN premium + insurer-count XLSX and normalize to Records."""
        import pandas as pd
        import requests

        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []

        def _ym(row) -> Optional[str]:
            mes = _MESES.get(str(row["MES"]).strip().lower())
            return f'{int(row["AÑO"])}-{mes}' if mes else None

        # Premiums by ramo (RD$, monthly)
        r = requests.get(_CKAN_PRIMAS_XLSX, headers={"User-Agent": _UA}, timeout=45)
        r.raise_for_status()
        primas = pd.read_excel(io.BytesIO(r.content))
        ramo_cols = [c for c in primas.columns if c not in ("AÑO", "MES")]
        for _, row in primas.iterrows():
            p = _ym(row)
            if not p or (period and p != period):
                continue
            total = 0.0
            for c in ramo_cols:
                v = row[c]
                val = None if pd.isna(v) else float(v)
                if val is not None:
                    total += val
                out.append(Record(series="sis.primas.ramo", period=p, value=val,
                                   lineage=lineage, unit="RD$", dimension=_slugify(c)))
            out.append(Record(series="sis.primas.total_mensual", period=p, value=total,
                              lineage=lineage, unit="RD$"))

        # Active-insurer counts (max across ramos = firms operating that month)
        try:
            r2 = requests.get(_CKAN_RAMOS_XLSX, headers={"User-Agent": _UA}, timeout=45)
            r2.raise_for_status()
            counts = pd.read_excel(io.BytesIO(r2.content))
            ccols = [c for c in counts.columns if c not in ("AÑO", "MES")]
            for _, row in counts.iterrows():
                p = _ym(row)
                if not p or (period and p != period):
                    continue
                mx = max((int(row[c]) for c in ccols if not pd.isna(row[c])), default=None)
                out.append(Record(series="sis.aseguradoras.activas_max", period=p,
                                  value=None if mx is None else float(mx),
                                  lineage=lineage, unit="conteo"))
        except Exception as e:  # noqa: BLE001 — counts are secondary to premiums
            logger.warning("SIS ramos-count no disponible en live: %s", e)

        if series:
            out = [rec for rec in out if rec.series == series]
        return out

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        # Fixture: the committed real sample. Its per-ramo series are keyed
        # "sis.primas.ramo.<slug>"; normalize them to series="sis.primas.ramo"
        # + dimension=<slug> so live and fixture yield the same Record shape.
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for s_name, s in fixture.items():
            if s_name.startswith("_"):
                continue
            norm = "sis.primas.ramo" if s_name.startswith("sis.primas.ramo.") else s_name
            if series and norm != series:
                continue
            dim = s.get("dimension")
            unit = s.get("unit")
            for p, v in (s.get("observations") or {}).items():
                if period and p != period:
                    continue
                out.append(Record(series=norm, period=p,
                                  value=None if v is None else float(v),
                                  lineage=lineage, unit=unit, dimension=dim))
        return out


def ramo_label(slug: str) -> str:
    """Display label for a ramo slug (falls back to a title-cased slug)."""
    for s, label in RAMO_LABELS:
        if s == slug:
            return label
    return slug.replace("_", " ").title()
