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

#: Página de datos abiertos del emisor. Es la que se consulta para resolver el CSV vigente.
_SFS_INDICE = "https://cnss.gob.do/transparencia/estadisticas-institucionales/data-abierta/"

#: URL de respaldo, **congelada a propósito y declarada**. El CNSS renombra el archivo cada
#: mes con el último período en el nombre (`…_2007_Mayo-2026.csv`) y **deja el anterior en
#: pie**, así que una URL fija no falla: sigue respondiendo 200 y sirve una serie cada vez más
#: vieja. Cuando se detectó, ésta devolvía hasta 2026-03 mientras el emisor publicaba 2026-05
#: — dos meses de atraso que ningún error habría revelado. Es la falla más cara de este
#: repositorio: la que no avisa.
_SFS_CSV_RESPALDO = ("https://cnss.gob.do/wp-content/uploads/2023/06/"
                     "SFS_Afiliacion-por-Regimen_2007_MARZO-2026-.csv")

#: El nombre lleva el período final; el mes va en español y con mayúscula inicial variable
#: («MARZO», «Mayo»), así que se compara sin distinguir caso.
_RX_SFS = re.compile(
    r'href="([^"]*SFS_Afiliacion-por-Regimen[^"]*\.csv)"', re.I)

_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"


def resolver_csv_vigente(timeout: int = 45) -> tuple[str, str]:
    """`(url, procedencia)` del CSV que el emisor publica HOY.

    Se resuelve contra su índice en vez de fijarse, por la misma razón que el conector de la
    SIE resuelve el suyo contra el catálogo: la ruta lleva el período y cambia cada mes.

    La procedencia viaja con la URL y no es decorativa. Si hubo que caer al respaldo, quien
    consuma esto tiene que poder decir que la serie puede estar vieja — un respaldo que se usa
    en silencio es exactamente cómo un fallback se vuelve permanente, que en esta plataforma
    ya ocurrió con los «promedios del sistema».
    """
    import requests

    try:
        r = requests.get(_SFS_INDICE, headers={"User-Agent": _UA}, timeout=timeout)
        r.raise_for_status()
        halladas = _RX_SFS.findall(r.text)
    except Exception as e:                                   # red, DNS, 5xx
        logger.warning("SISALRIL: no se pudo resolver el CSV vigente (%s)", e)
        halladas = []
    if halladas:
        return halladas[0], "indice"
    return _SFS_CSV_RESPALDO, "respaldo"


def _num(s: str) -> Optional[float]:
    s = (s or "").strip().replace(",", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


class SISALRILClient(FixtureBackedClient):
    """SFS health-coverage connector (CNSS/SISALRIL)."""

    source = "SISALRIL"
    license = ("SISALRIL / CNSS — Open Database License (ODbL) v1.0: exige el aviso de atribución, "
        "y el share-alike alcanza a las bases DERIVADAS. Un informe o un gráfico es "
        "«Produced Work» y NO lo dispara (§4.5) — "
        "https://opendatacommons.org/licenses/odbl/1-0/")
    license_ok = True
    fixture_file = "sisalril.json"
    live_phase = "F1c (CNSS CSV live)"

    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        import pandas as pd
        import requests

        url, procedencia = resolver_csv_vigente()
        if procedencia == "respaldo":
            # Se declara y no se calla: la serie puede venir meses atrasada y el consumidor
            # tiene que poder decirlo.
            logger.warning("SISALRIL: se usa la URL de RESPALDO; la serie puede estar vieja")
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=60)
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
