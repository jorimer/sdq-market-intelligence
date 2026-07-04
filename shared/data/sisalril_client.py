"""SISALRIL / CNSS — connector for Dominican social health-insurance data (SFS).

The Family Health Insurance (Seguro Familiar de Salud, SFS) affiliation series are
published by CNSS on ``datos.gob.do`` as a messy multi-header CSV (title preamble +
nested headers, then monthly rows ``YYYYMM, Total, Subsidiado, Contributivo, …``).
This connector exposes the national coverage series behind the ``Record`` contract:

  * ``sfs.afiliacion.total``        — total population covered by the SFS (monthly)
  * ``sfs.afiliacion.contributivo`` — contributory regime (formal workers)
  * ``sfs.afiliacion.subsidiado``   — subsidized regime (state-funded)

These feed the health-coverage face of SDQ Seguros (SISALRIL sub-sector). The ARS
(health-risk-manager) entity rating is a separate, deferred track — its financials
live behind the SISALRIL REDATAM (Dash) portal, not in clean CKAN files.

``fixture`` mode (default) reads a committed real, cited sample (``sisalril.json``);
``live`` mode downloads + parses the CNSS CSV. Missing values stay ``None``.
"""
import io
import logging
import re
from datetime import date
from typing import List, Optional

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sisalril")

_SFS_CSV = ("https://cnss.gob.do/wp-content/uploads/2023/06/"
            "SFS_Afiliacion-por-Regimen_2007_MARZO-2026-.csv")
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"


def _num(s: str) -> Optional[float]:
    s = (s or "").strip().replace(",", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


class SISALRILClient(FixtureBackedClient):
    """SFS health-coverage connector (CNSS/SISALRIL)."""

    source = "SISALRIL"
    license = "https://opendatacommons.org/licenses/odbl/"
    license_ok = True
    fixture_file = "sisalril.json"
    live_phase = "F1c (CNSS CSV live)"

    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        import pandas as pd
        import requests

        r = requests.get(_SFS_CSV, headers={"User-Agent": _UA}, timeout=60)
        r.raise_for_status()
        raw = pd.read_csv(io.BytesIO(r.content), header=None, dtype=str, keep_default_na=False)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        # Columns: 0 period YYYYMM, 1 Total, 2 Subsidiado, 3 Contributivo.
        cols = {"sfs.afiliacion.total": (1, None),
                "sfs.afiliacion.subsidiado": (2, "subsidiado"),
                "sfs.afiliacion.contributivo": (3, "contributivo")}
        out: List[Record] = []
        for i in range(len(raw)):
            a = str(raw.iloc[i, 0]).strip()
            if not re.fullmatch(r"\d{6}", a):
                continue
            p = f"{a[:4]}-{a[4:]}"
            if period and p != period:
                continue
            for code, (col, dim) in cols.items():
                if series and code != series:
                    continue
                if col < raw.shape[1]:
                    v = _num(str(raw.iloc[i, col]))
                    out.append(Record(series=code, period=p, value=v, lineage=lineage,
                                      unit="personas", dimension=dim))
        return out

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for s_name, s in fixture.items():
            if s_name.startswith("_") or (series and s_name != series):
                continue
            for p, v in (s.get("observations") or {}).items():
                if period and p != period:
                    continue
                out.append(Record(series=s_name, period=p,
                                  value=None if v is None else float(v),
                                  lineage=lineage, unit=s.get("unit"), dimension=s.get("dimension")))
        return out
