"""Turn a BCRD report's extracted text into a structured AI digest.

Output schema (all in Spanish), consumed by the macro/banking insight engines
and the Publicaciones view::

    {
      "resumen": str,                       # 3-5 sentence executive summary
      "hallazgos": [str, ...],              # key findings
      "cifras": [{"etiqueta": str, "valor": str}, ...],
      "riesgos": [str, ...],                # risk signals / vulnerabilities
      "relevancia": {"<sector>": str, ...}  # why it matters per sector
    }
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from shared.config.settings import settings

logger = logging.getLogger("sdq.publications.digest")

_MAX_TOKENS = 4096

_PROMPT = (
    "Eres un analista senior del Caribe analizando un informe/estudio estadístico "
    "oficial de la República Dominicana ('{report_name}', período {period}).\n\n"
    "A partir del texto del informe, produce un análisis estructurado en español, "
    "objetivo y citando cifras concretas cuando existan. Responde ÚNICAMENTE con un "
    "objeto JSON válido (sin texto adicional, sin ```), con esta forma exacta:\n"
    '{{"resumen": "3-5 oraciones de resumen ejecutivo", '
    '"hallazgos": ["hallazgo clave", "..."], '
    '"cifras": [{{"etiqueta": "PIB", "valor": "5.1% interanual"}}], '
    '"riesgos": ["riesgo o vulnerabilidad", "..."], '
    '"relevancia": {{"{sector_hint}": "por qué importa para ese sector"}}}}\n\n'
    "Sé conciso: máx. 6 hallazgos, 8 cifras, 5 riesgos. "
    "Si el texto está incompleto o ilegible, refléjalo en 'resumen' y deja listas vacías.\n\n"
    "TEXTO DEL INFORME:\n{text}"
)

EMPTY_DIGEST: Dict[str, Any] = {
    "resumen": "", "hallazgos": [], "cifras": [], "riesgos": [], "relevancia": {},
}


def _extract_json(raw: str) -> Dict[str, Any]:
    """Parse the first JSON object from a model response.

    Scans tracking string state + a bracket stack so it ignores braces inside
    strings; if the response is truncated, closes any open string and brackets.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).rsplit("```", 1)[0].strip()
    start = raw.find("{")
    if start == -1:
        raise ValueError("respuesta sin JSON")
    s = raw[start:]

    stack: List[str] = []
    in_str = esc = False
    end: Optional[int] = None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                end = i
                break

    if end is not None:
        return json.loads(s[: end + 1])
    # Truncated: close the open string (if any) and remaining brackets.
    repaired = s + ('"' if in_str else "")
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return json.loads(repaired)


def normalize_digest(data: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a parsed digest into the canonical shape, dropping junk."""
    out = dict(EMPTY_DIGEST)
    out["resumen"] = str(data.get("resumen", "") or "")
    out["hallazgos"] = [str(x) for x in (data.get("hallazgos") or []) if x][:8]
    out["riesgos"] = [str(x) for x in (data.get("riesgos") or []) if x][:6]
    cifras: List[Dict[str, str]] = []
    for c in (data.get("cifras") or [])[:10]:
        if isinstance(c, dict) and (c.get("etiqueta") or c.get("valor")):
            cifras.append({"etiqueta": str(c.get("etiqueta", "")), "valor": str(c.get("valor", ""))})
    out["cifras"] = cifras
    rel = data.get("relevancia") or {}
    out["relevancia"] = {str(k): str(v) for k, v in rel.items() if v} if isinstance(rel, dict) else {}
    return out


def build_digest(
    text: str,
    report_name: str,
    period: str,
    sectors: tuple = ("macro",),
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:  # pragma: no cover - AI call
    """Call Claude to summarize *text* into the structured digest schema."""
    key = api_key or settings.ANTHROPIC_API_KEY
    if not key:
        raise ValueError("Se requiere ANTHROPIC_API_KEY para generar el digest.")
    if not text.strip():
        return dict(EMPTY_DIGEST)

    import anthropic

    client = anthropic.Anthropic(api_key=key)
    prompt = _PROMPT.format(
        report_name=report_name,
        period=period,
        sector_hint=sectors[0] if sectors else "macro",
        text=text,
    )
    resp = client.messages.create(
        model=model or settings.ANTHROPIC_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text if resp.content else ""
    try:
        return normalize_digest(_extract_json(raw))
    except Exception as e:  # noqa: BLE001 — never fail ingestion on a digest parse error
        logger.warning("[digest] no se pudo parsear el JSON del modelo: %s", e)
        d = dict(EMPTY_DIGEST)
        d["resumen"] = raw.strip()[:1000]
        return d
