"""Descomposición SEMÁNTICA de dominios — el Cerebro decide qué motores convoca la pregunta.

El motor de research es tema-primero: una pregunta casi nunca se contesta con un solo motor
(un riesgo de liquidez bancaria se transmite por el canal monetario y macro; una pregunta de
zonas francas + aranceles convoca comercio y macro). Hasta ahora esa convocatoria salía de un
mapa curado por reglas (``resolve.context_axes`` / ``_CONTEXT_FOR``). Este módulo da el salto:
el **Cerebro lee la pregunta** y elige, del catálogo REAL de motores del sistema, cuáles
convoca y por qué —con rol primario/contexto—, en vez de un mapa fijo.

Garantías (misma doctrina anti-fabricación que el resto del motor):
- El Cerebro sólo puede elegir ejes que EXISTEN e están IMPLEMENTADOS (se validan contra el
  catálogo; cualquier eje inventado se descarta).
- Fallback determinista: sin Cerebro, con error, o con respuesta inválida, no se pierde nada
  —``resolve`` ya sembró el contexto curado y el merge es aditivo (unión, no reemplazo)—.
- El resultado se UNE al contexto curado: el piso de reglas nunca desaparece; el Cerebro sólo
  puede AGREGAR dominios (y su razón), nunca quitar los conocidos-buenos.

Anti-Frankenstein: el catálogo sale del registro de productos; no se importa ningún módulo de
sector.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.registry import CATALOG_BY_KEY, PRODUCT_CATALOG

logger = logging.getLogger("sdq.research.domain_router")

# Máximo de dominios que una pregunta puede convocar. Cota anti-dilución: un dictamen que
# integra 3-4 motores es síntesis; uno que arrastra 8 es ruido (y latencia de pulls).
_MAX_DOMAINS = 5

# Brief de ruteo por eje: en UNA línea, qué RESPONDE cada motor. Es doctrina de ruteo (no de
# sector) — le da al Cerebro la señal para elegir. Un eje sin brief cae a display_name+fuente.
_ENGINE_BRIEF: Dict[str, str] = {
    "banking": "Solidez, rating, liquidez, mora y eficiencia de un banco o del sistema bancario.",
    "macro": "Riesgo-país, inflación, PIB, fiscal, reservas, tipo de cambio, gobernanza (IRMP).",
    "monetary_policy": "Postura del BCRD: tasa de política (TPM), sesgo y trayectoria monetaria.",
    "trade": "Comercio exterior: exportaciones, importaciones, balanza, aranceles, socios.",
    "tourism": "Turismo: llegadas, ocupación, ingresos por divisas del sector.",
    "free_zones": "Zonas francas y manufactura de exportación (CNZFE).",
    "energy": "Energía eléctrica: generación, matriz, renovables, cobertura.",
    "telecom": "Telecomunicaciones: penetración móvil/banda ancha, conectividad.",
    "construction": "Construcción y vivienda: cemento, permisos, actividad del sector.",
    "agribusiness": "Agropecuario y agroindustria.",
    "esg": "Riesgo climático y resiliencia (IRC nacional): clima, ambiental, adaptación.",
    "pension": "Pensiones (SIPEN/AFP): rentabilidad, cotizantes, fondos, solvencia previsional.",
    "insurance": "Seguros (SIS): primas, siniestralidad, solvencia de aseguradoras.",
    "economic_structure": "Estructura de la economía: peso y aporte de cada sector al PIB.",
}

_SYSTEM = (
    "Sos el enrutador de dominios del motor de research de SDQ (inteligencia financiera de "
    "República Dominicana). Dada una pregunta libre de un comprador y el CATÁLOGO de motores "
    "disponibles, elegís qué motores la pregunta convoca y con qué rol. Regla dura: elegí "
    "SÓLO motores del catálogo (usá su clave 'eje' EXACTA); no inventes ejes. Sé selectivo: "
    "la mayoría de las preguntas convocan 2-4 motores. 'primario' = el dominio del que trata "
    "la pregunta; 'contexto' = un dominio cuyo estado sistémico condiciona la respuesta (el "
    "canal de transmisión). Respondé SÓLO un objeto JSON, sin texto alrededor."
)

_USER = (
    "PREGUNTA:\n{question}\n\nCATÁLOGO DE MOTORES (elegí sólo de acá, por su clave 'eje'):\n"
    "{catalog}\n\nDevolvé JSON con esta forma EXACTA:\n"
    '{{"dominios": [{{"eje": "<clave del catálogo>", "rol": "primario|contexto", '
    '"por_que": "<en una frase, por qué la pregunta lo convoca / el canal de transmisión>"}}]}}'
)


@dataclass
class RoutedDomain:
    """Un motor que la pregunta convoca, según el Cerebro."""

    sector_key: str
    role: str          # "primary" | "context"
    reason: str = ""


def _catalog_menu() -> str:
    """Menú legible de los motores del catálogo (clave · qué responde). El Cerebro elige de acá.
    Se lista el catálogo completo: un eje sin implementar no devuelve dato y se descarta solo en
    la cosecha (``pull_axis``), sin ensuciar la síntesis."""
    lines: List[str] = []
    for e in PRODUCT_CATALOG:
        brief = _ENGINE_BRIEF.get(e.sector_key) or f"{e.display_name} (fuente: {e.source})"
        lines.append(f"- {e.sector_key}: {brief}")
    return "\n".join(lines)


def _extract_obj(raw: str) -> Optional[Dict[str, Any]]:
    """Primer objeto JSON de la respuesta del modelo (tolera fences y prosa alrededor)."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).rsplit("```", 1)[0].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_domains(obj: Dict[str, Any]) -> List[RoutedDomain]:
    """Valida la respuesta contra el catálogo IMPLEMENTADO. Descarta ejes inventados/duplicados."""
    out: List[RoutedDomain] = []
    seen: set = set()
    for item in (obj.get("dominios") or [])[: _MAX_DOMAINS * 2]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("eje") or "").strip()
        if not key or key in seen or key not in CATALOG_BY_KEY:
            continue  # anti-fabricación: sólo ejes reales del catálogo
        seen.add(key)
        rol = str(item.get("rol") or "").strip().lower()
        role = "primary" if rol.startswith("prim") else "context"
        reason = str(item.get("por_que") or item.get("porque") or "").strip()
        out.append(RoutedDomain(sector_key=key, role=role, reason=reason))
        if len(out) >= _MAX_DOMAINS:
            break
    return out


# Caché en memoria del ruteo por pregunta. Crítico para la caché de RESPUESTAS aguas abajo:
# el ruteo es una llamada LLM — sin caché (y con temperatura) dos corridas de la MISMA
# pregunta pueden convocar dominios distintos → contexto de síntesis distinto → la caché del
# narrative_engine nunca pega y cada re-consulta idéntica paga el LLM completo (hallado
# midiendo en prod: la "warm" tardaba igual que la fría). Acotada (FIFO) para no crecer.
_ROUTE_CACHE: Dict[str, List[RoutedDomain]] = {}
_ROUTE_CACHE_MAX = 256


def _route_cache_key(question: str) -> str:
    return " ".join(question.lower().split())


async def route_domains(question: str, db: Optional[Session]) -> List[RoutedDomain]:
    """Dominios que la pregunta convoca según el Cerebro (validados contra el catálogo). Lista
    vacía si no hay Cerebro, hay error, o la respuesta es inválida → el orquestador se queda
    con el contexto curado de ``resolve`` (degradación transparente, sin pérdida).

    Cacheado por pregunta y con ``temperature=0``: el ruteo debe ser ESTABLE — misma pregunta,
    mismos dominios — para que la caché de narrativas aguas abajo funcione."""
    if not question or not question.strip():
        return []
    key = _route_cache_key(question)
    cached = _ROUTE_CACHE.get(key)
    if cached is not None:
        return list(cached)
    from shared.config.settings import settings
    from shared.narrative.claude_engine import narrative_engine

    client = narrative_engine._get_client()
    if client is None:
        return []  # sin API key → fallback determinista (contexto curado)

    system = _SYSTEM
    user = _USER.format(question=question.strip(), catalog=_catalog_menu())
    try:
        async with narrative_engine._get_sem():
            resp = await asyncio.to_thread(
                client.messages.create,
                model=settings.ANTHROPIC_MODEL,
                max_tokens=600,
                temperature=0.0,  # ruteo estable entre corridas (clasificación, no prosa)
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        raw = "".join(getattr(b, "text", "") for b in (resp.content or []))
    except Exception as e:  # noqa: BLE001 — cualquier fallo del API → fallback determinista
        logger.warning("route_domains: fallo del Cerebro (%s); fallback al contexto curado.", e)
        return []

    obj = _extract_obj(raw)
    if not obj:
        logger.info("route_domains: respuesta sin JSON válido; fallback al contexto curado.")
        return []
    routed = _parse_domains(obj)
    if len(_ROUTE_CACHE) >= _ROUTE_CACHE_MAX:
        _ROUTE_CACHE.pop(next(iter(_ROUTE_CACHE)))
    _ROUTE_CACHE[key] = list(routed)
    return routed


def merge_routing(targets, routed: List[RoutedDomain]) -> None:
    """UNE los dominios del Cerebro al ``Targets`` ya sembrado por ``resolve`` (mutación in-situ).

    Aditivo, nunca sustractivo: el contexto curado se conserva; el Cerebro sólo AGREGA. Un
    dominio ya cubierto por una entidad resuelta no se re-agrega como pull de sistema (pero sí
    aporta su razón). primario→``axes`` (pull a-nivel-sistema), contexto→``context``; los dos
    alimentan la síntesis por igual, la distinción es para narrar el canal."""
    if not routed:
        return
    entity_sectors = {e.sector_key for e in targets.entities}
    reasons: Dict[str, str] = getattr(targets, "reasons", None) or {}
    for d in routed:
        if d.reason and d.sector_key not in reasons:
            reasons[d.sector_key] = d.reason
        if d.sector_key in entity_sectors:
            continue  # ya lo trae la entidad como pull primario
        if d.sector_key in targets.axes or d.sector_key in targets.context:
            continue  # ya sembrado por resolve (curado) — no duplicar
        if d.role == "primary":
            targets.axes.append(d.sector_key)
        else:
            targets.context.append(d.sector_key)
    targets.reasons = reasons
