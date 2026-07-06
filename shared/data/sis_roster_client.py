"""SIS — official roster of authorized insurers / reinsurers.

The Superintendencia de Seguros publishes the directory of authorized aseguradoras and
reaseguradoras at ``sis.gob.do/companias-aseguradoras-y-reaseguradoras/`` (an HTML table
with name + address per company). This is the AUTHORITATIVE active set — used as the
canonical identity for the ISF so the rating shows exactly the official companies with
their official names (robust to the audited sheet-name truncation and to defunct insurers
lingering in the multi-year history).

``fixture`` mode reads the committed real sample (``sis_roster.json``); ``live`` mode
scrapes the page. Exposes ``official_insurers() -> List[str]`` (official names).
"""
import logging
import re
from typing import List

logger = logging.getLogger("sdq.data.sis_roster")

_URL = "https://sis.gob.do/companias-aseguradoras-y-reaseguradoras/"
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"
_FIXTURE = "sis_roster.json"

_ADDR = re.compile(r"\s+(?:Av\.|Av\s|Ave\.|Avenida|Calle|C/|C\.\s|Tel\.|Tels\.|Email|"
                   r"Apartado|Edif\.|Salvador|Ens\.|Urb\.|No\.)")
_TERM = re.compile(r"^(.+?(?:INC\.?|S\.\s?A\.?))(\s*\([^)]+\))?", re.S)


def _clean_name(cell: str) -> str:
    nm = _ADDR.split(cell, maxsplit=1)[0].strip()
    m = _TERM.match(nm)
    if m:
        nm = (m.group(1).strip() + " " + (m.group(2) or "").strip()).strip()
    return re.sub(r"\s+", " ", nm).rstrip(",")


def _parse_live() -> List[str]:
    import pandas as pd
    import requests

    r = requests.get(_URL, headers={"User-Agent": _UA}, timeout=45)
    r.raise_for_status()
    from io import StringIO
    tables = pd.read_html(StringIO(r.text))
    names: List[str] = []
    for t in tables:
        for col in t.columns:
            for v in t[col].dropna():
                if len(str(v)) > 20:
                    n = _clean_name(str(v))
                    if n and n not in names:
                        names.append(n)
    return sorted(names)


def official_insurers(mode: str = "fixture") -> List[str]:
    """The official authorized-insurer names. ``live`` scrapes the SIS directory; ``fixture``
    (default) reads the committed sample. Live failure falls back to the fixture."""
    if mode == "live":
        try:
            names = _parse_live()
            if names:
                return names
        except Exception as e:  # noqa: BLE001
            logger.warning("Roster SIS live falló (%s); uso fixture", e)
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent / "fixtures" / _FIXTURE
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(json.load(fh).get("companies") or [])
