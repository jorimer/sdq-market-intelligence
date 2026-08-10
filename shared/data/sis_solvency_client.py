"""SIS — Índices de Solvencia y Liquidez (Ley 146-02, Cap. XII, Art. 164).

The Superintendencia de Seguros publishes, per insurer, the REGULATORY solvency and
liquidity indices (Art. 164) as downloadable Excel — an audited annual file + four
quarterly files per year, under /transparencia/indices-de-solvencia-y-liquidez/.

Per Ley 146-02:
  * **Índice de Solvencia** = Patrimonio Técnico Ajustado (Art. 161) / Margen de
    Solvencia Mínima Requerida (Art. 160). ``≥ 1`` = compliant.
  * **Índice de Liquidez** = Disponibilidad Libre de Gravamen / Liquidez Mínima
    Requerida (Art. 162). ``≥ 1`` = compliant.

This connector exposes both indices per insurer, carrying the OFFICIAL company name
(``dimension`` = display name) so the sync can match to the audited-financials roster.
``N/R`` (no reporta) and the ``TOTAL``/footnote rows are dropped. Missing values stay None.
"""
import io
import logging
import re
from datetime import date
from typing import Dict, List, Optional

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sis_solvency")

_FOLDER = "https://sis.gob.do/transparencia/indices-de-solvencia-y-liquidez/{year}-2/"
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"
# Column layout (header at row ~16): 0 Compañía · 4 Índice de Solvencia · 8 Índice de Liquidez
_COL_NAME, _COL_SOLV, _COL_LIQ = 0, 4, 8


def brand_key(name: str) -> str:
    """Aggressive normalized key for cross-source insurer matching: strip corporate
    and generic-insurance tokens (incl. common abbreviations), keep the brand tokens."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.,]", " ", s)
    drop = {"s", "a", "sa", "c", "por", "cxa", "inc", "srl", "de", "del", "la", "el", "y",
            "compania", "cia", "comp", "seguros", "seguro", "seg", "reaseguros", "reaseguro",
            "reaseg", "aseguradora", "aseg", "dominicana", "dominicano", "society", "insurance",
            "company", "co"}
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in drop]
    return "_".join(toks)


# Formas societarias. Se descartan siempre; a diferencia de ``drop``, acá NO van las
# palabras del rubro, porque para la clave compacta son parte del nombre comercial.
_FORMAS = {"s", "a", "sa", "c", "por", "cxa", "inc", "srl", "ltd", "sas"}


def brand_key_compacta(name: str) -> str:
    """Clave alternativa que CONSERVA las palabras del rubro y las pega sin separador.

    ``brand_key`` descarta "seguro(s)" por genérica, lo cual es correcto en general pero
    parte los nombres donde el rubro ES la marca: «Auto Seguro, S. A.» queda en ``auto``
    —cuatro letras— y no parea con «Autoseguro, S.A.» del roster, porque el matcher exige
    cinco caracteres para arriesgar un prefijo. Pegando los tokens, ambas dan ``autoseguro``.

    Se usa SOLO como coincidencia EXACTA de último recurso: sin prefijos ni primer token, un
    match compacto no puede inventar parentescos entre compañías distintas.

    >>> brand_key_compacta("Auto Seguro, S. A.") == brand_key_compacta("Autoseguro, S.A.")
    True
    """
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _FORMAS]
    return "".join(toks)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


class SISSolvencyClient(FixtureBackedClient):
    """Índices de Solvencia y Liquidez connector (per insurer)."""

    source = "SIS"
    license = "https://sis.gob.do (público)"
    license_ok = True
    fixture_file = "sis_solvency.json"
    live_phase = "solvencia (índices SIS live)"

    def _discover_url(self) -> Optional[tuple]:
        """Return ``(url, period)`` for the latest audited índices file, else the latest
        quarterly. Scrapes the year folders from the current year backwards."""
        import datetime

        import requests
        for y in range(datetime.date.today().year, 2019, -1):
            try:
                r = requests.get(_FOLDER.format(year=y), headers={"User-Agent": _UA}, timeout=45)
                if r.status_code != 200:
                    continue
                files = re.findall(r'href="(https?://[^"]*Indices-de-Solvencia-y-Liquidez[^"]*\.xlsx)"',
                                   r.text, flags=re.I)
                if not files:
                    continue
                aud = next((f for f in files if "auditado" in f.lower()), None)
                if aud:
                    return aud, str(y)
                # else the highest quarter
                q = sorted(files, key=lambda f: f.lower())[-1]
                return q, str(y)
            except Exception as e:  # noqa: BLE001
                logger.warning("Índices solvencia %s no accesible: %s", y, e)
        return None

    def _parse(self, content: bytes, period: str, lineage: Lineage) -> List[Record]:
        import pandas as pd

        df = pd.read_excel(io.BytesIO(content), header=None)
        out: List[Record] = []
        for i in range(len(df)):
            name = df.iloc[i, _COL_NAME]
            if pd.isna(name) or not str(name).strip():
                continue
            nm = str(name).strip()
            low = nm.lower()
            if nm.upper() == "TOTAL" or low.startswith("la presente") or "compañías" in low \
                    or "companias" in low:
                continue
            solv = _num(df.iloc[i, _COL_SOLV]) if df.shape[1] > _COL_SOLV else None
            liq = _num(df.iloc[i, _COL_LIQ]) if df.shape[1] > _COL_LIQ else None
            if solv is None and liq is None:
                continue
            for code, val in (("indice_solvencia", solv), ("indice_liquidez", liq)):
                out.append(Record(series=code, period=period, value=val, lineage=lineage,
                                  unit="ratio", dimension=nm))
        return out

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        if self.mode == "live":
            import requests
            found = self._discover_url()
            if not found:
                raise RuntimeError("No se encontró el archivo de Índices de Solvencia y Liquidez")
            url, per = found
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=90)
            r.raise_for_status()
            recs = self._parse(r.content, per, lineage)
        else:
            fx = self._load_fixture(self.fixture_file)
            per = fx.get("period", "—")
            recs = []
            for _, rec in (fx.get("entities") or {}).items():
                for code in ("indice_solvencia", "indice_liquidez"):
                    v = rec.get(code)
                    recs.append(Record(series=code, period=per, value=v, lineage=lineage,
                                      unit="ratio", dimension=rec.get("name")))
        if series:
            recs = [r for r in recs if r.series == series]
        if period:
            recs = [r for r in recs if r.period == period]
        return recs
