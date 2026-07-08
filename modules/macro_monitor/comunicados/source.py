"""Descubrimiento y extracción de los Comunicados de Política Monetaria del BCRD.

El BCRD publica cada decisión de TPM como un artículo HTML en su Sala de Prensa (no
PDF). Listado y detalle se sirven por el mismo endpoint AJAX del CMS (mini-ng):

    POST /Home/GetContentForRender   (application/x-www-form-urlencoded)
        id=<article_id>&languageName=es

La respuesta es JSON con caracteres de control embebidos → se parsea con
``strict=False``. El listado (contenedor ``LISTING_ID = 2576``) devuelve los
artículos hijo *newest-first* en
``result.dynamicContent.articleList.articleList.items``; el detalle (id numérico del
comunicado) devuelve el cuerpo en ``result.article.content``.

El **nivel de TPM y el sentido de la decisión** se derivan de forma DETERMINISTA del
título/cuerpo (:func:`parse_decision`) — la IA interpreta el racional, nunca cuenta
el número. Verificado contra el sitio 2026-07-08.
"""
from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import httpx

logger = logging.getLogger("sdq.comunicados.source")

BASE = "https://www.bancentral.gov.do"
ENDPOINT = f"{BASE}/Home/GetContentForRender"
LISTING_ID = 2576  # contenedor "Sala de prensa / Comunicados de política monetaria"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SDQ-MIP/1.0)",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Verbo del titular → sentido de la decisión (normalizado).
_HOLD = ("mantiene", "mantuvo", "mantener")
_CUT = ("reduce", "redujo", "reducir", "baja", "disminuye", "recorta")
_HIKE = ("incrementa", "incrementó", "aumenta", "aumentó", "sube", "eleva", "eleva")

PostFn = Callable[[int], Dict]


@dataclass(frozen=True)
class ComunicadoRef:
    """Un comunicado en el listado (metadatos, sin el cuerpo)."""
    article_id: int
    string_id: str          # "6606-bcrd-mantiene-...-525--anual"
    title: str
    date_iso: Optional[str]  # fecha del comunicado (auxiliarDatetime1), YYYY-MM-DD
    preview: str            # resumen corto (previewContent, texto plano)

    @property
    def url(self) -> str:
        return f"{BASE}/a/d/{self.string_id}"


@dataclass(frozen=True)
class ComunicadoDetail:
    """El comunicado con su cuerpo (racional) en texto plano."""
    article_id: int
    title: str
    subtitle: str
    body_text: str
    url: str


def _post(article_id: int, timeout: int = 30) -> Dict:  # pragma: no cover - network I/O
    """POST al endpoint del CMS y devuelve el JSON (tolerante a chars de control)."""
    resp = httpx.post(ENDPOINT, headers=_HEADERS,
                      data={"id": article_id, "languageName": "es"},
                      timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return json.loads(resp.text, strict=False)


def _html_to_text(raw: str) -> str:
    """HTML → texto plano legible (colapsa espacios, desescapa entidades)."""
    if not raw:
        return ""
    txt = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)  # descarta scripts/estilos
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n\n", txt).strip()


def _date_iso(raw: Optional[str]) -> Optional[str]:
    """'2026-06-30T00:00:00Z' → '2026-06-30'. Ignora el centinela 0001-01-01."""
    if not raw or raw.startswith("0001"):
        return None
    return raw[:10]


def list_comunicados(limit: int = 50, *, post: PostFn = _post) -> List[ComunicadoRef]:
    """Los comunicados del listado, *newest-first*. ``limit`` recorta desde el más reciente.

    El endpoint devuelve ~50 por página (``totalCount`` total); para el uso recurrente
    los más recientes bastan. Ordena por fecha del comunicado desc (con id como
    desempate) por si el CMS no garantiza el orden.
    """
    payload = post(LISTING_ID)
    items = (payload.get("result", {}).get("dynamicContent", {})
             .get("articleList", {}).get("articleList", {}).get("items", []))
    refs: List[ComunicadoRef] = []
    for it in items:
        try:
            aid = int(it["id"])
        except (KeyError, TypeError, ValueError):
            continue
        refs.append(ComunicadoRef(
            article_id=aid,
            string_id=str(it.get("stringId") or aid),
            title=(it.get("title") or "").strip(),
            date_iso=_date_iso(it.get("auxiliarDatetime1")),
            preview=_html_to_text(it.get("previewContent") or ""),
        ))
    refs.sort(key=lambda r: (r.date_iso or "", r.article_id), reverse=True)
    return refs[:limit] if limit else refs


def fetch_detail(article_id: int, *, post: PostFn = _post) -> ComunicadoDetail:
    """El cuerpo (racional) de un comunicado, en texto plano."""
    art = post(article_id).get("result", {}).get("article", {})
    return ComunicadoDetail(
        article_id=article_id,
        title=(art.get("title") or "").strip(),
        subtitle=_html_to_text(art.get("subtitle") or ""),
        body_text=_html_to_text(art.get("content") or ""),
        url=f"{BASE}/a/d/{article_id}",
    )


def parse_decision(title: str, body_text: str = "") -> Dict[str, Optional[object]]:
    """Deriva DETERMINÍSTICAMENTE ``{action, tpm_level, bps_change}`` del titular (+ cuerpo).

    - ``action``: 'hold' | 'cut' | 'hike' | None (según el verbo del titular).
    - ``tpm_level``: nivel resultante de la TPM en % (float). En "de A % a B %" toma B
      (el último %); en "mantiene … en X %" toma X. Si el titular solo da el cambio en
      puntos básicos, lo busca en el cuerpo. None si no aparece.
    - ``bps_change``: magnitud del cambio en puntos básicos (int), si el texto lo indica.
    """
    t = (title or "").lower()
    action: Optional[str] = None
    if any(v in t for v in _HOLD):
        action = "hold"
    elif any(v in t for v in _CUT):
        action = "cut"
    elif any(v in t for v in _HIKE):
        action = "hike"

    def _last_pct(s: str) -> Optional[float]:
        m = re.findall(r"(\d+[.,]\d+)\s*%", s)
        return float(m[-1].replace(",", ".")) if m else None

    # El nivel resultante está al final del titular ("… a 5.25 % anual" / "en 5.25 %").
    tpm_level = _last_pct(title)
    if tpm_level is None:  # p.ej. "incrementa … en 25 puntos básicos" (sin nivel en el titular)
        m = re.search(r"(?:TPM|tasa de (?:inter[eé]s de )?pol[ií]tica monetaria)[^.%]{0,60}?"
                      r"(\d+[.,]\d+)\s*%", body_text, re.I)
        tpm_level = float(m.group(1).replace(",", ".")) if m else None

    # Solo cut/hike tienen magnitud de cambio. En un 'hold' el cuerpo suele mencionar
    # "puntos básicos" por otras tasas (corredor) o decisiones previas → no es el cambio.
    # El titular del cut/hike lo declara ("reduce … en 25 puntos básicos"); si no, el cuerpo.
    bps_change: Optional[int] = None
    if action in ("cut", "hike"):
        bps = (re.search(r"(\d{1,3})\s*puntos\s+b[aá]sicos", title, re.I)
               or re.search(r"(\d{1,3})\s*puntos\s+b[aá]sicos", body_text, re.I))
        bps_change = int(bps.group(1)) if bps else None

    return {"action": action, "tpm_level": tpm_level, "bps_change": bps_change}
