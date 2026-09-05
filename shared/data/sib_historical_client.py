"""Loader for the SIB *Cronología SB* historical financial ledger.

The Superintendencia de Bancos published (Jul 2026) a historical microportal whose
statistics module is backed by **raw public CSVs** — the per-entity *monthly*
balance sheet (``estado de situación``, 1947→) and income statement
(``estado de resultados``, 1996→). This module downloads those CSVs, normalises
the two (slightly different) schemas into a single long-format row, and loads them
into :class:`SibHistoricalLedger` idempotently.

Design notes
------------
* **Two schemas.** Balance carries four ``DETALLE_NIVEL`` levels and ``MONTO``;
  resultados carries two levels plus ``MONTO`` and ``MONTO_DESAGREGADO``.
* **Streaming.** Files are up to ~140 MB, so parsing is row-by-row via the stdlib
  ``csv`` reader (no pandas in the prod path); the download streams to a temp file.
* **Idempotency.** A load replaces all rows for a given ``source_file`` before
  inserting, so re-running a fresh snapshot never duplicates. ``row_key`` (sha1 of
  the natural key) is a second-line integrity guard that behaves the same on
  SQLite and Postgres regardless of the NULL levels resultados leaves behind.

This is a landing zone only — a downstream crosswalk derives ``banking_data`` rows
(``source=sib_historical``) from it; see ``docs/SIB_HISTORICO_FASE1_DISENO.md``.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import os
import tempfile
from datetime import date, datetime
from typing import Dict, Iterable, Iterator, List, Optional

from shared.data.base_client import check_license_for

logger = logging.getLogger("sdq.external.sib_historical")

# Régimen de uso del dato, registrado en `shared/data/licenses.py`. Los términos del
# portal (leídos el 2026-09-04) son un descargo sobre exactitud, no una prohibición de
# redistribuir; el pie «Todos los derechos reservados» es plantilla de OGTIC y no fija
# el régimen del dato público dominicano.
SOURCE = "SB"
LICENSE = ("SB — estadísticas del sistema financiero publicadas por la Superintendencia de "
           "Bancos: portal institucional, series históricas y SIMBAD. Información pública "
           "dominicana: reutilizable con atribución por Ley 200-04, Decreto 103-22, NORTIC A3 "
           "y Ley 65-00 art. 41.")
LICENSE_OK = True

# ── Source registry (public media URLs, snapshot 2026-07-19) ─────────
# Kept explicit rather than scraped: the microportal is a static snapshot and the
# URLs are stable content-addressed paths. Re-verify with a HEAD if a load 404s
# (the SB CDN has renamed assets without notice before — see bcrd-publications).
SNAPSHOT_DATE = date(2026, 7, 19)

FILES: List[Dict[str, str]] = [
    {"estado": "situacion", "periods": "1947_1996",
     "url": "https://sb.gob.do/media/dhegzna3/estadosituacion_1947_1996.csv"},
    {"estado": "situacion", "periods": "1997_2006",
     "url": "https://sb.gob.do/media/t33d0eg5/estadosituacion_1997_2006.csv"},
    {"estado": "situacion", "periods": "2007_2016",
     "url": "https://sb.gob.do/media/sl0ausa0/estadosituacion_2007_2016.csv"},
    {"estado": "situacion", "periods": "2017_2026",
     "url": "https://sb.gob.do/media/odxbssia/estadosituacion_2017_2026.csv"},
    {"estado": "resultados", "periods": "1996_2005",
     "url": "https://sb.gob.do/media/zjllbxvd/estadoresultados_1996_2005.csv"},
    {"estado": "resultados", "periods": "2006_2015",
     "url": "https://sb.gob.do/media/odajojsb/estadoresultados_2006_2015.csv"},
    {"estado": "resultados", "periods": "2016_2026",
     "url": "https://sb.gob.do/media/w25c2vrp/estadoresultados_2016_2026.csv"},
]


def source_file_name(rec: Dict[str, str]) -> str:
    return f"estado{rec['estado']}_{rec['periods']}.csv"


# ── Normalisation helpers ────────────────────────────────────────────

def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    return s or None


def _norm_tipo(s: Optional[str]) -> Optional[str]:
    """Collapse the casing drift the SB introduced from 2017 on.

    The same type appears as 'Bancos Múltiples', 'BANCOS MÚLTIPLES' and
    'Bancos múltiples' across files; canonicalise to Title-ish form so the
    downstream matcher sees one value. Accents are preserved (they are part of
    the official label); only casing is unified.
    """
    s = _clean(s)
    if not s:
        return None
    # Title-case each word but keep short connectors lowercase.
    small = {"de", "y", "del", "la", "las", "los"}
    out = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        out.append(lw if (i and lw in small) else lw.capitalize())
    return " ".join(out)


def _parse_num(s: Optional[str]) -> Optional[float]:
    s = _clean(s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        # Some locales use thousands separators; strip and retry.
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None


def _parse_date(s: Optional[str]) -> Optional[date]:
    s = _clean(s)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _row_key(estado: str, fecha: str, ent: str, n1, n2, n3, n4) -> str:
    raw = "|".join([estado, fecha or "", ent or "", n1 or "", n2 or "", n3 or "", n4 or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ── Parsing ──────────────────────────────────────────────────────────

def parse_rows(fileobj: Iterable[str], estado: str, source_file: str,
               snapshot_date: date = SNAPSHOT_DATE) -> Iterator[Dict]:
    """Yield normalised ledger-row dicts from an open CSV text stream.

    Works for both schemas: resultados simply lacks NIVEL_3/4 (left NULL) and
    carries an extra ``MONTO_DESAGREGADO``.
    """
    reader = csv.DictReader(fileobj)
    for raw in reader:
        # DictReader keys may carry a BOM on the first column; normalise access.
        def g(*names):
            for n in names:
                if n in raw:
                    return raw[n]
                for k in raw:
                    if k.lstrip("﻿") == n:
                        return raw[k]
            return None

        fecha_s = _clean(g("FECHA"))
        ent = _clean(g("ENTIDAD"))
        if not fecha_s or not ent:
            continue  # a malformed/blank line — skip rather than poison the load
        n1 = _clean(g("DETALLE_NIVEL_1"))
        n2 = _clean(g("DETALLE_NIVEL_2"))
        n3 = _clean(g("DETALLE_NIVEL_3"))
        n4 = _clean(g("DETALLE_NIVEL_4"))
        ano = g("ANO")
        mes = g("MES")
        yield {
            "estado": estado,
            "fecha": _parse_date(fecha_s),
            "ano": int(ano) if ano and str(ano).strip().isdigit() else None,
            "mes": int(mes) if mes and str(mes).strip().isdigit() else None,
            "periodicidad": _clean(g("PERIODICIDAD")),
            "entidad_code": ent,
            "entidad_nombre": _clean(g("NOMBRE_ENTIDAD")),
            "tipo_entidad": _norm_tipo(g("TIPO_ENTIDAD")),
            "sector": _clean(g("SECTOR_ENTIDAD")),
            "tipo_capital": _clean(g("TIPO_CAPITAL")),
            "nivel_1": n1,
            "nivel_2": n2,
            "nivel_3": n3,
            "nivel_4": n4,
            "monto": _parse_num(g("MONTO")),
            "monto_desagregado": _parse_num(g("MONTO_DESAGREGADO")),
            "snapshot_date": snapshot_date,
            "source_file": source_file,
            "row_key": _row_key(estado, fecha_s, ent, n1, n2, n3, n4),
        }


# ── Download ─────────────────────────────────────────────────────────

def download_to_temp(url: str, timeout: float = 600.0) -> str:
    """Stream a CSV to a temp file and return its path. Caller deletes it."""
    check_license_for(SOURCE, LICENSE, LICENSE_OK)
    import httpx

    fd, path = tempfile.mkstemp(suffix=".csv", prefix="sib_hist_")
    os.close(fd)
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)
    return path


# ── Loading ──────────────────────────────────────────────────────────

def load_file(db, rec: Dict[str, str], *, local_path: Optional[str] = None,
              batch_size: int = 5000, replace: bool = True) -> int:
    """Load one source file into ``sib_historical_ledger`` idempotently.

    ``local_path`` bypasses the download (used by tests and for re-loading an
    already-downloaded snapshot). Returns the number of rows inserted.
    """
    from modules.banking_score.models.models import SibHistoricalLedger

    source_file = source_file_name(rec)
    tmp = None
    try:
        path = local_path or (tmp := download_to_temp(rec["url"]))
        if replace:
            db.query(SibHistoricalLedger).filter(
                SibHistoricalLedger.source_file == source_file
            ).delete(synchronize_session=False)
            db.flush()

        inserted = 0
        buf: List[Dict] = []
        seen_keys: set = set()
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in parse_rows(fh, rec["estado"], source_file):
                # Guard against duplicate natural keys within the same file so the
                # unique(row_key) constraint can't abort a whole batch.
                if row["row_key"] in seen_keys:
                    continue
                seen_keys.add(row["row_key"])
                buf.append(row)
                if len(buf) >= batch_size:
                    db.bulk_insert_mappings(SibHistoricalLedger, buf)
                    db.flush()
                    inserted += len(buf)
                    buf = []
        if buf:
            db.bulk_insert_mappings(SibHistoricalLedger, buf)
            db.flush()
            inserted += len(buf)
        db.commit()
        logger.info("sib_historical: %s → %d filas", source_file, inserted)
        return inserted
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def sync_all(db, *, only_estado: Optional[str] = None) -> Dict[str, int]:
    """Download and load every historical file. Returns {source_file: rows}."""
    result: Dict[str, int] = {}
    for rec in FILES:
        if only_estado and rec["estado"] != only_estado:
            continue
        try:
            result[source_file_name(rec)] = load_file(db, rec)
        except Exception as e:  # one file failing shouldn't abort the rest
            logger.warning("sib_historical: %s falló: %s", source_file_name(rec), e)
            result[source_file_name(rec)] = -1
    return result
