"""SISALRIL BDFINAC — connector for the ARS (health-risk-manager) financial statements.

The SISALRIL Portal Estadístico exposes the *Estado Financiero de las Administradoras
de Riesgos de Salud* (base ``BDFINAC``) via a clean REST download endpoint that returns
a ZIP with a tidy CSV (``ARS_ID, AN_ID, MES_ID, ARS_N, ARS_CAT, PERIODO, PLAN_NO, TIPO,
VALOR``) + a variable dictionary. History Sep-2007 → present, 18 ARS.

Account schema (``TIPO``, per the published dictionary):
    6 = Inversiones que avalan el margen de solvencia   7 = Margen de solvencia requerido
    11 = Beneficio o pérdidas netas   12 = Ingreso en salud   13 = Gasto en salud
    (also 1-5,8-10 balance-sheet accounts — a regulatory trial balance whose stock/flow
     mix per plan is not fully documented, so patrimonial solvency stays a DECLARED GAP.)
Plans (``PLAN_NO``): 0 = entity base (balance/margin), 1 = Todos los Planes (health flows).

This connector exposes only the WELL-DEFINED regulatory metrics per ARS/period:
    ars.margen_inversiones (6, plan 0) · ars.margen_requerido (7, plan 0)
    ars.beneficio_neto (11, plan 1) · ars.ingreso_salud (12, plan 1) · ars.gasto_salud (13, plan 1)
carried as per-entity ``Record``s (ARS_ID in ``dimension``). Missing values stay ``None``.
``ARS_CAT``: 1 = Autogestionada, 2 = Pública, 3 = Privada — exposed via ``ars_categories()``.
"""
import io
import logging
import zipfile
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.sisalril_ars")

_DL = "https://redatam.sisalril.gob.do/api/bases-de-datos/download"
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"

# TIPO (account) → series code, and the PLAN_NO the figure is read from. These accounts
# reproduce SISALRIL's official regulatory indicators (validated: margen 6/7 == portal
# indicator 405 exactly): 405 = 6/7, 401 = 13/12, 409 ROE = 11/10.
_ACCOUNTS: Dict[int, Tuple[str, int]] = {
    6: ("ars.margen_inversiones", 0),
    7: ("ars.margen_requerido", 0),
    10: ("ars.patrimonio", 0),
    11: ("ars.beneficio_neto", 1),
    12: ("ars.ingreso_salud", 1),
    13: ("ars.gasto_salud", 1),
}
ARS_CAT_LABELS = {1: "Autogestionada", 2: "Pública", 3: "Privada"}

# Official ARS_ID → name, from the SISALRIL Portal Estadístico (indicator 405, toggle
# Codificados↔Etiquetados: the indicator codes equal the BDFINAC ARS_ID). Authoritative.
ARS_NAMES = {
    "001": "ARS CMD (Colegio Médico Dominicano)",
    "003": "ARS APS",
    "005": "ARS Simag",
    "006": "ARS Grupo Médico Asociado (GMA)",
    "013": "ARS Dr. Yunén",
    "014": "ARS Universal",
    "018": "ARS Monumental",
    "021": "ARS Futuro",
    "023": "ARS Primera",
    "036": "ARS ASEMAP (Amor y Paz)",
    "042": "ARS SEMMA",
    "043": "ARS Renacer",
    "049": "Mapfre Salud ARS",
    "050": "ARS Plan Salud Banco Central",
    "052": "ARS SeNaSa",
    "056": "ARS Reservas",
    "063": "ARS MetaSalud",
    "147": "IDOPPRIL (Riesgos Laborales)",
}


def ars_name(ars_id: str, category=None) -> str:
    """Official ARS name for a BDFINAC ARS_ID; falls back to a coded label."""
    n = ARS_NAMES.get(str(ars_id).zfill(3)) or ARS_NAMES.get(str(ars_id))
    if n:
        return n
    return f"ARS {ars_id}" + (f" ({ARS_CAT_LABELS.get(category, '')})" if category else "")


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def ars_categories() -> Dict[str, int]:
    """``{ars_id: category}`` from the committed fixture (1/2/3)."""
    fx = SISALRILARSClient(mode="fixture")._load_fixture(SISALRILARSClient.fixture_file)
    return {a: r.get("cat") for a, r in (fx.get("entities") or {}).items()}


class SISALRILARSClient(FixtureBackedClient):
    """ARS financial-statement connector (BDFINAC)."""

    source = "SISALRIL"
    license = "https://opendatacommons.org/licenses/odbl/"
    license_ok = True
    fixture_file = "sisalril_ars.json"
    live_phase = "ARS (BDFINAC live)"

    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Discover the latest available period, download the BDFINAC ZIP for a recent
        window, parse the CSV → per-ARS Records. Best-effort period discovery."""
        import datetime

        import pandas as pd
        import requests

        # Discover p_fin: walk back from the current month until a download succeeds.
        today = datetime.date.today()
        p_fin = None
        content = b""
        for back in range(0, 8):
            y = today.year + ((today.month - 1 - back) // 12)
            mo = (today.month - 1 - back) % 12 + 1
            cand = f"{y}{mo:02d}"
            p_inicio = f"{y - 4}{mo:02d}"
            params = {"base": "BDFINAC", "periodo_col": "PERIODO", "fecha_fin": cand,
                      "object_name": f"BDFINAC/csv/BDFINAC{cand}.csv",
                      "rotulo": "Estado Financiero", "p_inicio": p_inicio, "p_fin": cand}
            try:
                r = requests.get(_DL, params=params, headers={"User-Agent": _UA}, timeout=90)
                if r.status_code == 200 and r.content[:2] == b"PK":  # a real ZIP
                    p_fin, content = cand, r.content
                    break
            except Exception as e:  # noqa: BLE001
                logger.warning("BDFINAC intento %s falló: %s", cand, e)
        if not content:
            raise RuntimeError("BDFINAC: no se pudo descargar ningún período reciente")

        zf = zipfile.ZipFile(io.BytesIO(content))
        csv_name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
        df = pd.read_csv(io.BytesIO(zf.read(csv_name)), dtype=str)
        df.columns = [c.replace("﻿", "") for c in df.columns]
        df["V"] = df["VALOR"].map(_num)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for _, row in df.iterrows():
            try:
                tipo, plan = int(row["TIPO"]), int(row["PLAN_NO"])
            except (TypeError, ValueError):
                continue
            spec = _ACCOUNTS.get(tipo)
            if not spec or spec[1] != plan:
                continue
            code, _ = spec
            if series and code != series:
                continue
            p = str(row["PERIODO"])
            per = f"{p[:4]}-{p[4:]}"
            if period and per != period:
                continue
            v = row["V"]
            out.append(Record(series=code, period=per, value=None if v is None else float(v),
                              lineage=lineage, unit="RD$", dimension=str(row["ARS_ID"])))
        return out

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        fx = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for ars_id, rec in (fx.get("entities") or {}).items():
            for code, obs in (rec.get("series") or {}).items():
                full = code if code.startswith("ars.") else f"ars.{code}"
                if series and full != series:
                    continue
                for p, v in obs.items():
                    if period and p != period:
                        continue
                    out.append(Record(series=full, period=p,
                                      value=None if v is None else float(v),
                                      lineage=lineage, unit="RD$", dimension=str(ars_id)))
        return out
