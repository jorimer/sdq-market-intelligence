"""Load the BCRD statistics catalog (``catalog_data.json``, shipped in this package).

The catalog is the discovered inventory of ~708 historical Excel files grouped by
sector, each entry a CDN URL. This module flattens it into ``CatalogEntry`` rows
the engine can iterate over.

The JSON lives *inside* this package (not under ``docs/``) and is resolved relative
to ``__file__`` so it ships with the code and works regardless of the working
directory or what the Docker image copies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_DEFAULT_CATALOG = Path(__file__).resolve().parent / "catalog_data.json"


@dataclass(frozen=True)
class CatalogEntry:
    sector: str
    url: str

    @property
    def filename(self) -> str:
        return self.url.split("/")[-1].split("?")[0]

    @property
    def ext(self) -> str:
        return Path(self.filename).suffix.lower()


def load_catalog(path: Path | str = _DEFAULT_CATALOG) -> List[CatalogEntry]:
    """Flatten the catalog JSON into ``CatalogEntry`` rows (supported extensions)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries: List[CatalogEntry] = []
    for sector, payload in data.items():
        files = payload.get("files", []) if isinstance(payload, dict) else []
        for url in files:
            if not isinstance(url, str):
                continue
            entry = CatalogEntry(sector=sector, url=url)
            if entry.ext in (".xlsx", ".xls"):
                entries.append(entry)
    return entries


def find_entry(filename: str, path: Path | str = _DEFAULT_CATALOG) -> Optional[CatalogEntry]:
    """Locate a catalog entry by (case-insensitive) filename."""
    target = filename.lower()
    for e in load_catalog(path):
        if e.filename.lower() == target:
            return e
    return None
