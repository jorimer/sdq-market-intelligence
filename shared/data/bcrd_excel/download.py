"""Fetch BCRD Excel files from the public CDN, cached to disk.

The statistics files live at ``cdn.bancentral.gov.do`` and are public (no token,
no IP allowlist — unlike the MacroVariables API). We cache by filename so a
re-run of the catalog doesn't re-download unchanged files.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger("sdq.data.bcrd_excel.download")

DEFAULT_CACHE_DIR = Path("data/bcrd_excel/cache")
_TIMEOUT = httpx.Timeout(60.0)


def fetch_excel(url: str, cache_dir: Path | str = DEFAULT_CACHE_DIR,
                force: bool = False) -> Path:
    """Download *url* into *cache_dir* and return the local path (cached)."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    name = url.split("/")[-1].split("?")[0] or "download.xlsx"
    dest = cache / name
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    logger.info("[bcrd_excel] descargando %s", url)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    if dest.stat().st_size == 0:
        raise ValueError(f"Descarga vacía: {url}")
    return dest
