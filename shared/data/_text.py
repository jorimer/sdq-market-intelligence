"""Shared text helpers for data connectors.

Two utilities that several ONE/BCRD connectors need and used to duplicate:

* :func:`norm` — accent/case/whitespace-insensitive key for matching provider
  labels (so spacing / accent / casing variants of a renamed source label still
  match). The single implementation; ``one_client`` and ``bcrd_sectors`` keep a
  private copy for now and migrate here in a follow-up cleanup.
* :func:`find_media_xlsx` — resolve the current ``/media/<hash>/<slug>.xlsx`` link
  for one or more filename fragments on an ONE Umbraco landing page. The media
  hash rotates, so the link is scraped, not hard-coded; when several revisions
  match the same fragment the latest coverage end-year wins (deterministic).
"""
import re
import unicodedata
from html import unescape
from typing import Dict

_MEDIA_XLSX_RE = re.compile(r"/media/[a-z0-9]+/[^\"'> ]+?\.xlsx", re.IGNORECASE)


def norm(s: object) -> str:
    """Strip accents, casefold, collapse whitespace — tolerant matching key."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def _end_year(path: str) -> int:
    """Highest 4-digit year in a filename (its coverage end), or 0."""
    return max((int(y) for y in re.findall(r"(?:19|20)\d{2}", path)), default=0)


def find_media_xlsx(html_text: str, fragments: Dict[str, str]) -> Dict[str, str]:
    """``{key: /media/<hash>/<slug>.xlsx}`` matching each *fragments* value in *html_text*.

    *fragments* is ``{key: fragment}``; the fragment is matched accent/case-insensitively
    against each ``.xlsx`` link's normalized path (so a rotated media hash is followed
    automatically). When several revisions match the same fragment (e.g.
    ``…-2008-2023`` and ``…-2008-2024``) the latest end-year wins. A fragment that
    isn't found is simply absent from the result — never fabricated.
    """
    norm_fragments = {key: norm(frag) for key, frag in fragments.items()}
    best: Dict[str, tuple] = {}  # key -> (end_year, path)
    for raw in sorted({unescape(m) for m in _MEDIA_XLSX_RE.findall(html_text)}):
        n = norm(raw)
        for key, frag in norm_fragments.items():
            if frag in n:
                ey = _end_year(raw)
                if key not in best or ey > best[key][0]:
                    best[key] = (ey, raw)
    return {key: path for key, (_ey, path) in best.items()}
