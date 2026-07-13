"""Reporte profundo — el motor de research reutiliza TODA la narrativa Deep Dive del
producto y le agrega la capa a-medida (orquestador v3).

Por qué: a US$7–10k por encargo, el entregable debe superar un Deep Dive, no ser un
resumen. En vez de re-escribir, este módulo:
1. Pide el CONTENIDO Deep Dive completo de la entidad vía ``assemble_product_content``
   (todas las secciones ya narradas por el Cerebro del producto + su procedencia).
2. Antepone la RESPUESTA A LA PREGUNTA (la capa de research: el ángulo que el comprador
   pidió, p.ej. liquidez) y aumenta Limitaciones con la brecha prospectiva.
3. Arma gráficos/tablas desde el snapshot real.
El resultado = Deep Dive íntegro + capa de research = más profundo que un Deep Dive.

Anti-Frankenstein: usa el contrato del registro (``get_product`` + ``assemble_product_content``);
no importa el módulo del sector. Los títulos de sección son data local (no se importa el
módulo solo por rótulos)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.products.registry import CATALOG_BY_KEY, get_product
from shared.products.tiers import ProductTier
from shared.research.data_pull import EnginePull
from shared.research.models import DeclaredGap
from shared.research.narrate import narrate_answer
from shared.research.resolve import ResolvedEntity

logger = logging.getLogger("sdq.research.deep_report")

# Rótulos de sección (data local — copiada, no importada del módulo). Cubre las claves
# Deep Dive de banca + las estándar + la capa de research. Fallback: key.title().
SECTION_TITLES: Dict[str, str] = {
    "respuesta_a_su_pregunta": "Respuesta a su pregunta",
    "executive_summary": "Resumen ejecutivo",
    "solidez_financiera": "Solidez financiera",
    "calidad_activos": "Calidad de activos",
    "eficiencia_rentabilidad": "Eficiencia y rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
    "comparative": "Posición vs pares",
    "entorno_operativo": "Entorno operativo",
    "soporte_soberano": "Soporte y techo soberano",
    "risk_assessment": "Evaluación de riesgo",
    "early_warning": "Alerta temprana",
    "recommendation": "Recomendaciones",
    "limitations": "Limitaciones",
    "std_methodology": "Metodología y fuentes",
    "std_sources": "Fuentes y referencias",
}

# Secciones deterministas del producto (no pasan por el Cerebro) → siempre reales.
_ALWAYS_KEEP = {"early_warning", "limitations", "std_methodology", "std_sources"}


def _looks_real(text: str) -> bool:
    """Heurística anti-slop: una sección de análisis real CITA cifras. Los fallbacks del
    Cerebro (genérico o por-sección) son prosa genérica sin números de la entidad. Sin
    ``model_used`` en el dict de narrativas, esto distingue análisis real de relleno."""
    import re
    return len(re.findall(r"\d", text or "")) >= 4

SECTION_TITLES["metodologia"] = "Metodología y fuentes"
SECTION_TITLES["limitaciones"] = "Limitaciones"
SECTION_TITLES["dictamen"] = "Dictamen integrado"
SECTION_TITLES["evidencia"] = "Evidencia por motor"

_SYNTH_METHODOLOGY = (
    "Este informe INTEGRA el resultado ya computado de varios motores del sistema SDQ "
    "—{engines}— alrededor de la pregunta. No es la ficha de un sector: es la síntesis de "
    "los mecanismos de transmisión entre dominios, que ningún producto individual entrega. "
    "El Cerebro redactó circunscrito a esas cifras (verificador numérico activo: no se cita "
    "ningún número que no trace al dato de un motor). Sin web abierta ni fuentes externas en "
    "vivo. Lo que ningún motor computa se declara como límite, no se rellena.")

_METHODOLOGY_TEXT = (
    "La respuesta se ancló al resultado ya computado por el motor de la entidad "
    "(fuente: {source}) — rating, sub-componentes, percentiles vs pares, alerta temprana — "
    "y el Cerebro la redactó circunscrita a esas cifras (verificador numérico activo: no se "
    "cita ningún número que no trace al dato del motor). Sin web abierta ni fuentes externas "
    "en vivo. Lo que ningún motor computa se declara como límite, no se rellena.")

_LIMITATIONS_TEXT = (
    "La calificación es una medida de fortaleza financiera intrínseca (standalone) sobre "
    "información pública supervisada a la fecha de corte; no es un rating de crédito ni una "
    "recomendación de inversión. El análisis se circunscribe a los indicadores que el motor "
    "computa; lo prospectivo (proyecciones/escenarios a futuro) no se estima.")

_SUB_LABELS = {
    "solidez": "Solidez", "calidad": "Calidad de activos", "eficiencia": "Eficiencia",
    "liquidez": "Liquidez", "diversificacion": "Diversificación",
}


@dataclass
class DeepReport:
    entity_label: str
    sector_key: str
    period: Optional[str]
    ordered_keys: List[str] = field(default_factory=list)
    sections: Dict[str, str] = field(default_factory=dict)
    titles: Dict[str, str] = field(default_factory=dict)
    charts: List[dict] = field(default_factory=list)
    tables: List[Tuple[str, List[List[str]]]] = field(default_factory=list)
    headline: str = ""
    sources: List[str] = field(default_factory=list)


def _fmt(v: Any) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def _charts_from_payload(payload: Dict[str, Any]) -> List[dict]:
    """Gráficos de marca desde el scoring_result real (barras de sub-componentes + línea de
    trayectoria si viene). Robusto: omite lo que no reconoce, no fabrica."""
    sr = (payload or {}).get("scoring_result") or {}
    charts: List[dict] = []
    sub = sr.get("sub_components") or {}
    if sub:
        items = [(_SUB_LABELS.get(k, k.title()), round(float(v), 1))
                 for k, v in sub.items() if isinstance(v, (int, float))]
        if items:
            charts.append({"title": "Sub-componentes del rating (0–100)", "items": items})
    tr = (sr.get("trayectorias") or {}).get("overall")
    series = _as_series(tr)
    if len(series) >= 2:
        charts.append({"title": "Trayectoria del score", "kind": "line", "items": series})
    return charts


def _as_series(tr: Any) -> List[Tuple[str, float]]:
    """Normaliza una trayectoria a ``[(período, valor)]`` desde varias formas posibles."""
    out: List[Tuple[str, float]] = []
    if isinstance(tr, dict):
        for k, v in tr.items():
            if isinstance(v, (int, float)):
                out.append((str(k), round(float(v), 1)))
    elif isinstance(tr, (list, tuple)):
        for it in tr:
            if isinstance(it, dict):
                p = it.get("period") or it.get("periodo") or it.get("label")
                val = it.get("score") if it.get("score") is not None else it.get("value")
                if p is not None and isinstance(val, (int, float)):
                    out.append((str(p), round(float(val), 1)))
            elif isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[1], (int, float)):
                out.append((str(it[0]), round(float(it[1]), 1)))
    return out


def _tables_from_payload(payload: Dict[str, Any]) -> List[Tuple[str, List[List[str]]]]:
    """Tablas de marca desde el snapshot real (concentración del sistema si viene)."""
    peer = (payload or {}).get("peer_block") or {}
    tables: List[Tuple[str, List[List[str]]]] = []
    if peer.get("cr5") is not None:
        tables.append((f"Concentración del sistema · {peer.get('metric_label', 'activos')}",
                       [["Métrica", "Valor"],
                        ["CR5 (5 mayores)", _fmt(peer.get("cr5"))],
                        ["CR10 (10 mayores)", _fmt(peer.get("cr10"))],
                        ["HHI", _fmt(peer.get("hhi"))]]))
    return tables


def _headline(payload: Dict[str, Any]) -> str:
    sr = (payload or {}).get("scoring_result") or {}
    tier, score = sr.get("rating_tier"), sr.get("overall_score")
    if tier and isinstance(score, (int, float)):
        return f"{tier} · {score:.1f}/100"
    return ""


async def build_synthesis_report(question: str, db: Optional[Session], targets,
                                 forward_gaps: List[DeclaredGap]) -> Optional[DeepReport]:
    """Research TEMA-PRIMERO: cosecha el dato real de TODOS los motores que la pregunta
    convoca (entidades + dominios de contexto: macro, monetario, …) y entrega un DICTAMEN
    INTEGRADO —los mecanismos de transmisión entre dominios— en vez de la ficha de un sector.
    Es lo que un Deep Dive estructuralmente no puede dar. ``None`` si no hay dato/Cerebro."""
    from shared.research.data_pull import pull_axis, pull_entity
    from shared.research.narrate import narrate_synthesis

    if db is None:
        return None
    pulls: List[EnginePull] = []
    for ent in targets.entities:
        pulls.append(pull_entity(db, ent))
    for ax in list(targets.axes) + list(targets.context):
        pulls.append(pull_axis(db, ax))
    live = [p for p in pulls if p.ok and p.payload]
    if not live:
        return None

    thesis = await narrate_synthesis(question, live,
                                     forward_gaps=[g.note for g in forward_gaps],
                                     reasons=getattr(targets, "reasons", None))
    if not thesis:
        return None  # sin Cerebro → el orquestador cae al ensamblado liviano

    sections: Dict[str, str] = {"dictamen": f"**Pregunta:** {question}\n\n{thesis}"}
    ordered = ["dictamen"]

    # Evidencia por motor (determinista, cifras reales de cada dominio cosechado).
    ev: List[str] = []
    for p in live:
        ev.append(f"### {p.entity_label} · {p.sector_key}")
        ev.extend(f"- {e.text}" for e in p.evidence[:4])
    sections["evidencia"] = "\n".join(ev)
    ordered.append("evidencia")

    engines = ", ".join(dict.fromkeys(p.source for p in live))
    sections["metodologia"] = _SYNTH_METHODOLOGY.format(engines=engines)
    ordered.append("metodologia")
    lim = _LIMITATIONS_TEXT
    if forward_gaps:
        lim += "\n\n**Fuera de alcance (declarado):**\n" + "\n".join(
            f"- {g.note}" for g in forward_gaps)
    sections["limitaciones"] = lim
    ordered.append("limitaciones")

    # Gráficos/tablas del motor primario con entidad (si lo hay).
    ent_pull = next((p for p in live if any(p.sector_key == e.sector_key
                     for e in targets.entities)), live[0])
    titles = {k: SECTION_TITLES.get(k, k.replace("_", " ").title()) for k in ordered}
    sources = list(dict.fromkeys(p.source for p in live))
    return DeepReport(
        entity_label=ent_pull.entity_label, sector_key=ent_pull.sector_key,
        period=ent_pull.period, ordered_keys=ordered, sections=sections, titles=titles,
        charts=_charts_from_payload(ent_pull.payload),
        tables=_tables_from_payload(ent_pull.payload),
        headline=_headline(ent_pull.payload), sources=sources,
    )


async def build_deep_report(question: str, db: Optional[Session],
                            entities: List[ResolvedEntity], pulls: List[EnginePull],
                            forward_gaps: List[DeclaredGap]) -> Optional[DeepReport]:
    """Reporte profundo de la PRIMERA entidad resuelta con dato de motor. ``None`` si ninguna
    entidad trae dato (→ el orquestador usa el ensamblado liviano).

    Núcleo confiable: la RESPUESTA profunda (un solo llamado, siempre real) + gráficos/tablas
    del dato ya recibido. Las secciones del Deep Dive del producto se AGREGAN solo si están
    tibias en caché (retornan rápido); en frío no se espera el burst que rate-limitea (§6:
    ni slop ni latencia por relleno que igual se filtraría)."""
    import asyncio

    if db is None or not entities:
        return None
    from shared.products.assembler import assemble_product_content

    for ent in entities:
        pull = next((p for p in pulls if p.sector_key == ent.sector_key
                     and p.ok and p.payload and p.entity_label == ent.label), None)
        if pull is None:
            continue
        product = get_product(ent.sector_key, db)
        payload = pull.payload
        entry = CATALOG_BY_KEY.get(ent.sector_key)
        source = entry.source if entry else ent.sector_key

        # Capa de research: la respuesta profunda a la pregunta (su ángulo), arriba de todo.
        lead = await narrate_answer(question, [pull],
                                    forward_gaps=[g.note for g in forward_gaps])
        sections: Dict[str, str] = {}
        ordered: List[str] = []
        if lead:
            sections["respuesta_a_su_pregunta"] = f"**Pregunta:** {question}\n\n{lead}"
            ordered.append("respuesta_a_su_pregunta")

        # Secciones del Deep Dive del producto — SOLO si la caché está tibia (retorno rápido).
        # En frío no se espera el burst de ~11 narrativas (rate limit → fallback que se filtra).
        try:
            content = await asyncio.wait_for(
                assemble_product_content(product, ProductTier.deep_dive, period="",
                                         scope=ent.scope_value, lang="es"),
                timeout=15.0)
        except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 — frío/no disponible
            logger.info("Deep Dive de %s no en caché tibia (%s); solo la respuesta profunda.",
                        ent.label, type(e).__name__)
            content = None
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

        if content is not None:
            # Anti-slop: una sección reutilizada entra solo si trae análisis REAL (cifras) o
            # es determinista; el fallback del Cerebro se omite.
            for k in (list(content.section_order) or list(content.narratives.keys())):
                text = content.narratives.get(k)
                if not text or k in sections:
                    continue
                if k in _ALWAYS_KEEP or _looks_real(text):
                    sections[k] = text
                    ordered.append(k)

        # Metodología/Limitaciones mínimas si el Deep Dive no las aportó (caché fría).
        if "std_methodology" not in sections and "limitations" not in sections:
            sections["metodologia"] = _METHODOLOGY_TEXT.format(source=source)
            ordered.append("metodologia")
            sections["limitaciones"] = _LIMITATIONS_TEXT
            ordered.append("limitaciones")

        # Aumenta Limitaciones con la brecha prospectiva declarada (§4), sin fabricar.
        if forward_gaps:
            extra = "\n\n**Fuera de alcance (declarado):**\n" + "\n".join(
                f"- {g.note}" for g in forward_gaps)
            key = "limitations" if "limitations" in sections else "limitaciones"
            if key in sections:
                sections[key] += extra
            else:
                sections[key] = extra.strip()
                ordered.append(key)

        titles = {k: SECTION_TITLES.get(k, k.replace("_", " ").title()) for k in ordered}
        return DeepReport(
            entity_label=ent.label, sector_key=ent.sector_key, period=pull.period,
            ordered_keys=ordered, sections=sections, titles=titles,
            charts=_charts_from_payload(payload), tables=_tables_from_payload(payload),
            headline=_headline(payload), sources=[source],
        )
    return None
