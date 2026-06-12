"""Download BCRD publication PDFs from the public CDN.

A browser-like User-Agent is used because the CDN/WAF rejects some default
clients. No auth/token: these are public documents.
"""
from __future__ import annotations

import logging
import tempfile

import httpx

logger = logging.getLogger("sdq.publications.fetcher")

_UA = "Mozilla/5.0 (compatible; SDQ-MIP/1.0)"
_HEADERS = {"User-Agent": _UA, "Accept": "application/pdf,*/*"}


def url_exists(url: str, timeout: int = 20) -> bool:  # pragma: no cover - network I/O
    """True if a HEAD request returns 200 with a PDF content type."""
    try:
        resp = httpx.head(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:
        logger.debug("HEAD %s falló: %s", url, e)
        return False
    if resp.status_code != 200:
        return False
    ctype = resp.headers.get("content-type", "").lower()
    return "pdf" in ctype or "octet-stream" in ctype


def download_pdf(url: str, timeout: int = 60) -> str:  # pragma: no cover - network I/O
    """Download *url* to a temp file and return its path. Raises on HTTP error."""
    resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    fd.write(resp.content)
    fd.flush()
    fd.close()
    logger.info("Descargado %s (%d bytes) → %s", url, len(resp.content), fd.name)
    return fd.name
